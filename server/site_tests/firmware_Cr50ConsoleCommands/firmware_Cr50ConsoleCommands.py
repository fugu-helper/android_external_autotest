# Copyright 2017 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging
import os
import re

from autotest_lib.client.common_lib import error
from autotest_lib.server.cros.faft.firmware_test import FirmwareTest


class firmware_Cr50ConsoleCommands(FirmwareTest):
    """
    Verify the cr50 console output for important commands.

    This test verifies the output of pinmux, help, gpiocfg. These are the main
    console commands we can use to check cr50 configuration.
    """
    version = 1

    BRDPROP_FORMAT = ['properties = (0x\d+)\s']
    HELP_FORMAT = [ 'Known commands:(.*)HELP LIST.*>']
    GENERAL_FORMAT = [ '\n(.*)>']
    COMPARE_LINES = '\n'
    COMPARE_WORDS = None
    TESTS = [
        ['pinmux', GENERAL_FORMAT, COMPARE_LINES],
        ['help', HELP_FORMAT, COMPARE_WORDS],
        ['gpiocfg', GENERAL_FORMAT, COMPARE_LINES],
    ]


    def initialize(self, host, cmdline_args):
        super(firmware_Cr50ConsoleCommands, self).initialize(host, cmdline_args)
        if not hasattr(self, 'cr50'):
            raise error.TestNAError('Test can only be run on devices with '
                                    'access to the Cr50 console')

        self.host = host
        self.missing = []
        self.extra = []
        self.state = {}


    def parse_output(self, output, split_str):
        """Split the output with the given delimeter and remove empty strings"""
        output = output.split(split_str) if split_str else output.split()
        cleaned_output = []
        for line in output:
            # Replace whitespace characters with one space.
            line = ' '.join(line.strip().split())
            if line:
                cleaned_output.append(line)
        return cleaned_output


    def get_output(self, cmd, regexp, split_str):
        """Return the cr50 console output"""
        output = self.cr50.send_command_get_output(cmd, regexp)[0][1].strip()

        # Record the original command output
        results_path = os.path.join(self.resultsdir, cmd)
        with open(results_path, 'w') as f:
            f.write(output)

        output = self.parse_output(output, split_str)
        if not len(output):
            raise error.TestFail('Could not get %s output' % cmd)
        return '\n'.join(output) + '\n'


    def get_expected_output(self, cmd, split_str):
        """Return the expected cr50 console output"""
        path = os.path.join(os.path.dirname(os.path.realpath(__file__)), cmd)
        ext_path = path + '.' + self.brdprop

        if os.path.isfile(ext_path):
            path = ext_path

        logging.info('reading %s', path)
        if not os.path.isfile(path):
            raise error.TestFail('Could not find output file for %s', cmd)

        with open(path, 'r') as f:
            contents = f.read()

        return self.parse_output(contents, split_str)


    def check_command(self, cmd, regexp, split_str):
        """Compare the actual console command output to the expected output"""
        expected_output = self.get_expected_output(cmd, split_str)
        output = self.get_output(cmd, regexp, split_str)
        missing = []
        for regexp in expected_output:
            match = re.search(regexp, output)
            if match:
                self.state.update(match.groupdict())

            # Remove the matching string from the output.
            output, n = re.subn('%s' % regexp, '', output, 1)
            if not n:
                missing.append(regexp)

        if len(missing):
            self.missing.append('%s-(%s)' % (cmd, ', '.join(missing)))
        output = output.strip()
        if len(output):
            self.extra.append('%s-(%s)' % (cmd, ', '.join(output.split('\n'))))


    def get_brdprop(self):
        """Save the board properties

        Cutoff the board property write protect bits. Those won't change the
        gpio or pinmux settings.
        """
        rv = self.cr50.send_command_get_output('brdprop', self.BRDPROP_FORMAT)
        brdprop = int(rv[0][1], 16)
        self.brdprop = hex(brdprop & 0xff)


    def run_once(self, host):
        err = []
        self.get_brdprop()
        for command, regexp, split_str in self.TESTS:
            self.check_command(command, regexp, split_str)

        if (not self.state.get('ccd_has_been_enabled', 0) and
            self.state.get('ccd_enabled', 0)):
            err.append('Inconsistent ccd settings')

        if len(self.missing):
            err.append('MISSING OUTPUT: ' + ', '.join(self.missing))
        if len(self.extra):
            err.append('EXTRA OUTPUT: ' + ', '.join(self.extra))

        logging.info(self.state)

        if len(err):
            raise error.TestFail('\t'.join(err))
