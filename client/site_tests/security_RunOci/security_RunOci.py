# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import contextlib
import glob
import json
import logging
import os
import pwd
import re
import shutil
import tempfile

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import autotemp, error

CONFIG_JSON_TEMPLATE = '''
{
    "ociVersion": "1.0.0-rc1",
    "platform": {
        "os": "linux",
        "arch": "all"
    },
    "process": {
        "terminal": true,
        "user": {
            "uid": 0,
            "gid": 0
        },
        "args": [
            %s
        ],
        "cwd": "/"
    },
    "root": {
        "path": "rootfs",
        "readonly": false
    },
    "hostname": "runc",
    "mounts": [
    {
        "destination": "/proc",
        "type": "proc",
        "source": "proc",
        "options": [
            "nodev",
            "noexec",
            "nosuid"
        ]
    },
    {
        "destination": "/dev",
        "type": "bind",
        "source": "/dev",
        "options": [
            "bind",
            "recursive"
        ]
    }
    ],
    "hooks": {},
    "linux": {
        "namespaces": [
        {
            "type": "cgroup"
        },
        {
            "type": "pid"
        },
        {
            "type": "network"
        },
        {
            "type": "ipc"
        },
        {
            "type": "user"
        },
        {
            "type": "uts"
        },
        {
            "type": "mount"
        }
        ],
        "resources": {
            "devices": [
                {
                    "allow": false,
                    "access": "rwm"
                },
                {
                    "allow": true,
                    "type": "c",
                    "major": 1,
                    "minor": 5,
                    "access": "r"
                }
            ]
        },
        "uidMappings": [
        {
            "hostID": 1000,
            "containerID": 0,
            "size": 1
        }
        ],
        "gidMappings": [
        {
            "hostID": 1000,
            "containerID": 0,
            "size": 1
        }
        ]
    }
}
'''

@contextlib.contextmanager
def bind_mounted_root(rootfs_path):
    utils.run(['mount', '--bind', '/', rootfs_path])
    yield
    utils.run(['umount', '-f', rootfs_path])


class security_RunOci(test.test):
    version = 1

    preserve_srcdir = True

    def run_test_in_dir(self, test_config, oci_path):
        """
        Executes the test in the given directory that points to an OCI image.
        """
        result = utils.run(
                ['/usr/bin/run_oci'] + ['-U'] + test_config['run_oci_args'].split() +
                [oci_path] + test_config.get('program_extra_argv', '').split(),
                ignore_status=True, stderr_is_expected=True, verbose=True,
                stdout_tee=utils.TEE_TO_LOGS, stderr_tee=utils.TEE_TO_LOGS)
        expected = test_config['expected_result'].strip()
        if result.stdout.strip() != expected:
            logging.error('stdout mismatch %s != %s',
                          result.stdout.strip(), expected)
            return False
        expected_err = test_config.get('expected_stderr', '').strip()
        if result.stderr.strip() != expected_err:
            logging.error('stderr mismatch %s != %s',
                          result.stderr.strip(), expected_err)
            return False
        return True


    def run_test(self, test_config):
        """
        Runs one test from the src directory.  Return 0 if the test passes,
        return 1 on failure.
        """
        chronos_uid = pwd.getpwnam('chronos').pw_uid
        td = autotemp.tempdir()
        os.chown(td.name, chronos_uid, chronos_uid)
        with open(os.path.join(td.name, 'config.json'), 'w') as config_file:
            config_file.write(CONFIG_JSON_TEMPLATE % test_config['program_argv'])
        rootfs_path = os.path.join(td.name, 'rootfs')
        os.mkdir(rootfs_path)
        os.chown(rootfs_path, chronos_uid, chronos_uid)
        with bind_mounted_root(rootfs_path):
            return self.run_test_in_dir(test_config, td.name)
        return False


    def run_once(self):
        """
        Runs each of the tests specified in the source directory.
        This test fails if any subtest fails. Sub tests exercise the run_oci
        command and check that the correct namespace mappings and mounts are
        made. If any subtest fails, this test will fail.
        """
        failed = []
        ran = 0
        for p in glob.glob('%s/test-*.json' % self.srcdir):
            name = os.path.basename(p)
            logging.info('Running: %s', name)
            if not self.run_test(json.load(file(p))):
                failed.append(name)
            ran += 1
        if ran == 0:
            failed.append('No tests found to run from %s!' % (self.srcdir))
        if failed:
            logging.error('Failed: %s', failed)
            raise error.TestFail('Failed: %s' % failed)
