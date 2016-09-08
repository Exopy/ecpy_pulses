# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# Copyright 2015-2016 by EcpyHqcLegacy Authors, see AUTHORS for more details.
#
# Distributed under the terms of the BSD license.
#
# The full license is in the file LICENCE, distributed with this software.
# -----------------------------------------------------------------------------
"""Task to transfer a sequence on an AWG.

"""
from __future__ import (division, unicode_literals, print_function,
                        absolute_import)

import os
from traceback import format_exc
from pprint import pformat

from atom.api import Value, Unicode, Dict, Float
from ecpy.tasks.api import InstrumentTask


class TransferPulseSequenceTask(InstrumentTask):
    """Build and transfer a pulse sequence to an instrument.

    """
    #: Sequence path for the case of sequence simply referenced.
    sequence_path = Unicode().tag(pref=True)

    #: Time stamp of the last modification of the sequence file.
    sequence_timestamp = Float().tag(pref=True)

    #: Sequence of pulse to compile and transfer to the instrument.
    sequence = Value()

    #: Global variable to use for the sequence.
    sequence_vars = Dict().tag(pref=True)

    def check(self, *args, **kwargs):
        """Check that the sequence can be compiled.

        """
        test, traceback = super(TransferPulseSequenceTask,
                                self).check(*args, **kwargs)
        err_path = self.path + '/' + self.name + '-'

        msg = 'Failed to evaluate {} ({}): {}'
        for k, v in self.sequence_vars.items():
            try:
                self.format_and_eval_string(v)
            except Exception:
                test = False
                traceback[err_path+k] = msg.format(k, v, format_exc())

        if test:
            res, missings, errors = self.sequence.evaluate_sequence()
            if not res:
                if missings:
                    msg = 'Those variables were never evaluated : %s'
                    errors['missings'] = msg % missings
                traceback[err_path+'compil'] = errors
                return False, traceback

        items = self.sequence.simplify_sequence()
        context = self.sequence.context
        res, infos, errors = context.compile_and_transfer_sequence(items)

        if not res:
            traceback[err_path+'compil'] = errors
            return False, traceback

        if self.sequence_path:
            if not (self.sequence_timestamp ==
                    os.path.getmtime(self.sequence_path)):
                msg = 'The sequence is outdated, consider refreshing it.'
                traceback[err_path+'outdated'] = msg

        return test, traceback

    def perform(self):
        """Compile the sequence.

        """
        seq = self.sequence
        context = seq.context
        for k, v in self.sequence_vars.items():
            self.sequence.external_vars[k] = self.format_and_eval_string(v)

        res, missings, errors = seq.evaluate_sequence()
        if not res:
            msg = 'The following variables were never computed : %s'
            errors['Unknown variables'] = msg % missings
            raise Exception('Failed to evaluate sequence :\n' +
                            pformat(errors))

        items = seq.simplify_sequence()
        res, infos, errors = context.compile_and_transfer_sequence(items,
                                                                   self.driver)
        if not res:
            raise Exception('Failed to compile sequence :\n' +
                            pformat(errors))

        for k, v in infos.items():
            self.write_in_database(k, v)

    def register_preferences(self):
        """Register the task preferences into the preferences system.

        """
        super(TransferPulseSequenceTask, self).register_preferences()

        if self.sequence:
            self.preferences['sequence'] =\
                self.sequence.preferences_from_members()

    update_preferences_from_members = register_preferences

    def traverse(self, depth=-1):
        """Reimplemented to also yield the sequence

        """
        infos = super(TransferPulseSequenceTask, self).traverse(depth)

        for i in infos:
            yield i

        for item in self.sequence.traverse():
            yield item

    @classmethod
    def build_from_config(cls, config, dependencies):
        """Rebuild the task and the sequence from a config file.

        """
        builder = cls.mro()[1].build_from_config.__func__
        task = builder(cls, config, dependencies)

        builder = dependencies['ecpy.pulses.items']['ecpy_pulses.RootSequence']
        conf = config['sequence']
        seq = builder.build_from_config(conf, dependencies)
        task.sequence = seq

        return task

    def _post_setattr_sequence(self, old, new):
        """Set up n observer on the sequence context to properly update the
        database entries.

        """
        entries = self.database_entries.copy()
        if old:
            old.unobserve('context', self._update_database_entries)
            if old.context:
                for k in old.context.list_sequence_infos():
                    del entries[k]
        if new:
            new.observe('context', self._update_database_entries)
            if new.context:
                entries.update(new.context.list_sequence_infos())

        if entries != self.database_entries:
            self.database_entries = entries

    def _update_database_entries(self, change):
        """Reflect in the database the sequence infos of the context.

        """
        entries = self.database_entries.copy()
        if change['oldvalue']:
            for k in change['oldvalue'].list_sequence_infos():
                del entries[k]
        if change['value']:
            context = change['value']
            entries.update(context.list_sequence_infos())

        self.database_entries = entries
