# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.bin import test
from autotest_lib.client.bin import factory_error as error

class factory_Fail(test.test):
    version = 1

    def run_once(self):
      # Stub test to report failure.
      raise error.TestFail("Factory suite has failed.");
