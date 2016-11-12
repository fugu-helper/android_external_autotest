# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import errno
import json
import logging
import os

from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib import global_config
from autotest_lib.client.common_lib.cros import dev_server
from autotest_lib.server import adb_utils
from autotest_lib.server import constants
from autotest_lib.server.cros import dnsname_mangler
from autotest_lib.server.hosts import adb_host
from autotest_lib.site_utils import sponge_utils

DEFAULT_ACTS_INTERNAL_DIRECTORY = 'tools/test/connectivity/acts'

CONFIG_FOLDER_LOCATION = global_config.global_config.get_config_value(
        'ACTS', 'acts_config_folder', default='')

TEST_DIR_NAME = 'tests'
FRAMEWORK_DIR_NAME = 'framework'
SETUP_FILE_NAME = 'setup.py'
CONFIG_DIR_NAME = 'autotest_config'
CAMPAIGN_DIR_NAME = 'autotest_campaign'
LOG_DIR_NAME = 'logs'
ACTS_EXECUTABLE_IN_FRAMEWORK = 'acts/bin/act.py'

ACTS_TESTPATHS_ENV_KEY = 'ACTS_TESTPATHS'
ACTS_LOGPATH_ENV_KEY = 'ACTS_LOGPATH'
ACTS_PYTHONPATH_ENV_KEY = 'PYTHONPATH'


def create_acts_package_from_current_artifact(test_station, job_repo_url,
                                              target_zip_file):
    """Creates an acts package from the build branch being used.

    Creates an acts artifact from the build branch being used. This is
    determined by the job_repo_url passed in.

    @param test_station: The teststation that should be creating the package.
    @param job_repo_url: The job_repo_url to get the build info from.
    @param target_zip_file: The zip file to create form the artifact on the
                            test_station.

    @returns An ActsPackage containing all the information about the zipped
             artifact.
    """
    build_info = adb_host.ADBHost.get_build_info_from_build_url(job_repo_url)

    return create_acts_package_from_artifact(
            test_station, build_info['branch'], build_info['target'],
            build_info['build_id'], job_repo_url, target_zip_file)


def create_acts_package_from_artifact(test_station, branch, target, build_id,
                                      job_repo_url, target_zip_file):
    """Creates an acts package from a specified branch.

    Grabs the packaged acts artifact from the branch and places it on the
    test_station.

    @param test_station: The teststation that should be creating the package.
    @param branch: The name of the branch where the artifact is to be pulled.
    @param target: The name of the target where the artifact is to be pulled.
    @param build_id: The build id to pull the artifact from.
    @param job_repo_url: The job repo url for where to pull build from.
    @param target_zip_file: The zip file to create on the teststation.

    @returns An ActsPackage containing all the information about the zipped
             artifact.
    """
    devserver_url = dev_server.AndroidBuildServer.get_server_url(job_repo_url)
    devserver = dev_server.AndroidBuildServer(devserver_url)
    devserver.trigger_download(target,
                               build_id,
                               branch,
                               files='acts.zip',
                               synchronous=True)

    download_ulr = os.path.join(job_repo_url, 'acts.zip')

    test_station.download_file(download_ulr, target_zip_file)

    return ActsPackage(test_station, target_zip_file)


def create_acts_package_from_zip(test_station, zip_location, target_zip_file):
    """Creates an acts package from an existing zip.

    Creates an acts package from a zip file that already sits on the drone.

    @param test_station: The teststation to create the package on.
    @param zip_location: The location of the zip on the drone.
    @param target_zip_file: The zip file to create on the teststaiton.

    @returns An ActsPackage containing all the information about the zipped
             artifact.
    """
    if not os.path.isabs(zip_location):
        zip_location = os.path.join(CONFIG_FOLDER_LOCATION, 'acts_artifacts',
                                    zip_location)

    remote_zip = test_station.send_file(zip_location, target_zip_file)

    return ActsPackage(test_station, remote_zip)


class ActsPackage(object):
    """A packaged version of acts on a teststation."""
    def __init__(self, test_station, zip_file_path):
        """
        @param test_station: The teststation this package is on.
        @param zip_file_path: The path to the zip file on the test station that
                              holds the package on the teststation.
        """
        self.test_station = test_station
        self.zip_file = zip_file_path

    def create_container(self,
                         container_directory,
                         internal_acts_directory=None):
        """Unpacks this package into a container.

        Unpacks this acts package into a container to run acts tests in.

        @param container_directory: The directory on the teststation to hold
                                    the container.
        @param internal_acts_directory: The directory inside of the package
                                        that holds acts.

        @returns: An ActsContainer with info on the unpacked acts container.
        """
        self.test_station.run('unzip "%s" -x -d "%s"' %
                              (self.zip_file, container_directory))

        return ActsContainer(self.test_station,
                             container_directory,
                             acts_directory=internal_acts_directory)


class ActsContainer(object):
    """A container for running acts tests with a contained version of acts."""
    def __init__(self, test_station, container_directory, acts_directory=None):
        """
        @param test_station: The test staiton this container is on.
        @param container_directory: The directory on the teststation this
                                    container operates out of.
        @param acts_directory: The directory within the container that holds
                               acts. If none then it defaults to
                               DEFAULT_ACTS_INTERNAL_DIRECTORY.
        """
        self.test_station = test_station

        if not acts_directory:
            acts_directory = DEFAULT_ACTS_INTERNAL_DIRECTORY

        if not os.path.isabs(acts_directory):
            self.acts_directory = os.path.join(container_directory,
                                               acts_directory)
        else:
            self.acts_directory = acts_directory

        self.container_directory = container_directory

        self.tests_directory = os.path.join(self.acts_directory, TEST_DIR_NAME)
        self.framework_directory = os.path.join(self.acts_directory,
                                                FRAMEWORK_DIR_NAME)
        self.config_location = os.path.join(self.container_directory,
                                            CONFIG_DIR_NAME)

        self.log_directory = os.path.join(self.container_directory,
                                          LOG_DIR_NAME)

        self.working_directory = os.path.join(self.container_directory,
                                              CONFIG_DIR_NAME)

        self.acts_file = os.path.join(self.framework_directory,
                                      ACTS_EXECUTABLE_IN_FRAMEWORK)

        self.setup_file = os.path.join(self.framework_directory,
                                       SETUP_FILE_NAME)

        self.configs = {}
        self.campaigns = {}

    def install_sl4a_apk(self, testbed):
        """Install sl4a to a test bed.

        @param testbed: The testbed of phones to install to.
        """
        for serial, adb_host in testbed.get_adb_devices().iteritems():
            adb_utils.install_apk_from_build(
                    adb_host,
                    constants.SL4A_APK,
                    constants.SL4A_PACKAGE,
                    package_name=constants.SL4A_PACKAGE)

    def get_test_paths(self):
        """Get all test paths within this container.

        Gets all paths that hold tests within the container.

        @returns: A list of paths on the teststation that hold tests.
        """
        get_test_paths_result = self.test_station.run('find %s -type d' %
                                                      self.tests_directory)
        test_search_dirs = get_test_paths_result.stdout.splitlines()
        return test_search_dirs

    def get_python_path(self):
        """Get the python path being used.

        Gets the python path that will be set in the enviroment for this
        container.

        @returns: A string of the PYTHONPATH enviroment variable to be used.
        """
        return '%s:$PYTHONPATH' % self.framework_directory

    def get_enviroment(self):
        """Gets the enviroment variables to be used for this container.

        @returns: A dictionary of enviroment variables to be used by this
                  container.
        """
        env = {ACTS_TESTPATHS_ENV_KEY: ':'.join(self.get_test_paths()),
               ACTS_LOGPATH_ENV_KEY: self.log_directory,
               ACTS_PYTHONPATH_ENV_KEY: self.get_python_path()}

        return env

    def upload_file(self, src, dst):
        """Uploads a file to be used by the container.

        Uploads a file from the drone to the test staiton to be used by the
        test container.

        @param src: The source file on the drone. If a relative path is given
                    it is assumed to exist in CONFIG_FOLDER_LOCATION.
        @param dst: The destination on the teststation. If a relative path is
                    given it is assumed that it is within the container.

        @returns: The full path on the teststation.
        """
        if not os.path.isabs(src):
            src = os.path.join(CONFIG_FOLDER_LOCATION, src)

        if not os.path.isabs(dst):
            dst = os.path.join(self.container_directory, dst)

        path = dst
        while len(path) > 1:
            path = os.path.dirname(path)
            result = self.test_station.run('mkdir "%s"' % path,
                                           ignore_status=True)
            if result.exit_status:
                break

        self.test_station.send_file(src, dst)

        return dst

    def upload_config(self, config_file):
        """Uploads a config file to the container.

        Uploads a config file to the config folder in the container.

        @param config_file: The config file to upload. This must be a file
                            within the autotest_config directory under the
                            CONFIG_FOLDER_LOCATION.

        @returns: The full path of the config on the test staiton.
        """
        full_name = os.path.join(CONFIG_DIR_NAME, config_file)

        full_path = self.upload_file(full_name, full_name)
        self.configs[config_file] = full_path

        return full_path

    def upload_campaign(self, campaign_file):
        """Uploads a campaign file to the container.

        Uploads a campaign file to the campaign folder in the container.

        @param campaign_file: The campaign file to upload. This must be a file
                              within the autotest_campaign directory under the
                              CONFIG_FOLDER_LOCATION.

        @returns: The full path of the campaign on the test staiton.
        """
        full_name = os.path.join(CAMPAIGN_DIR_NAME, campaign_file)

        full_path = self.upload_file(full_name, full_name)
        self.campaigns[campaign_file] = full_path

        return full_path

    def setup_enviroment(self, python_bin='python'):
        """Sets up the teststation system enviroment so the container can run.

        Prepares the remote system so that the container can run. This involves
        uninstalling all versions of acts for the version of python being
        used and installing all needed dependencies.

        @param python_bin: The python binary to use.
        """
        uninstall_command = '%s %s uninstall' % (python_bin, self.setup_file)
        install_deps_command = '%s %s install_deps' % (python_bin,
                                                       self.setup_file)

        self.test_station.run(uninstall_command)
        self.test_station.run(install_deps_command)

    def run_test(self,
                 testbed,
                 config,
                 campaign=None,
                 test_case=None,
                 extra_env={},
                 python_bin='python',
                 testbed_name=None,
                 timeout=7200):
        """Runs a test within the container.

        Runs a test within a container using the given settings.

        @param testbed: The testbed to use for testing.
        @param config: The name of the config file to use as the main config.
                       This should have already been uploaded with
                       upload_config. The string passed into upload_config
                       should be used here.
        @param campaign: The campaign file to use for this test. If none then
                         test_case is assumed. This file should have already
                         been uploaded with upload_campaign. The string passed
                         into upload_campaign should be used here.
        @param test_case: The test case to run the test with. If none then the
                          campaign will be used.
        @param extra_env: Extra enviroment variables to run the test with.
        @param python_bin: The python binary to execute the test with.
        @param testbed_name: The name of the test bed, if none then the name
                             of the actual test bed is used.
        @param timeout: How many seconds to wait before timing out.

        @returns: The results of the test run.
        """
        if not testbed_name:
            # If no override is given get the name from the hostname.
            hostname = testbed.hostname
            if dnsname_mangler.is_ip_address(hostname):
                testbed_name = hostname
            else:
                testbed_name = hostname.split('.')[0]

        if not config in self.configs:
            # Check if the config has been uploaded and upload if it hasn't
            self.upload_config(config)

        full_config = self.configs[config]

        if campaign:
            # When given a campaign check if it's upload.
            if not campaign in self.campaigns:
                self.upload_campaign(campaign)

            full_campaign = self.campaigns[campaign]
        else:
            full_campaign = None

        full_env = self.get_enviroment()

        # Setup enviroment variables.
        if extra_env:
            for k, v in extra_env.items():
                full_env[k] = extra_env

        logging.info('Using env: %s', full_env)
        exports = ('export %s=%s' % (k, v) for k, v in full_env.items())
        env_command = ';'.join(exports)

        # Make sure to execute in the working directory.
        command_setup = 'cd %s' % self.working_directory

        act_base_cmd = '%s %s -c %s -tb %s ' % (python_bin, self.acts_file,
                                                full_config, testbed_name)

        # Format the acts command based on what type of test is being run.
        if test_case and campaign:
            raise error.TestError(
                    'campaign and test_file cannot both have a value.')
        elif test_case:
            act_cmd = '%s -tc %s' % (act_base_cmd, test_case)
        elif campaign:
            act_cmd = '%s -tf %s' % (act_base_cmd, full_campaign)
        else:
            raise error.TestFail('No tests was specified!')

        # Format all commands into a single command.
        command_list = [command_setup, env_command, act_cmd]
        full_command = '; '.join(command_list)

        try:
            # Run acts on the remote machine.
            act_result = self.test_station.run(full_command, timeout=timeout)
            excep = None
        except Exception as e:
            # Catch any error to store in the results.
            act_result = None
            excep = e

        results_file = os.path.join(self.log_directory, testbed_name, 'latest',
                                    'test_run_summary.json')
        cat_log_result = self.test_station.run('cat %s' % results_file,
                                               ignore_status=True)
        if not cat_log_result.exit_status:
            json_results = json.loads(cat_log_result.stdout)
        else:
            json_results = {}

        return ActsTestResults(test_case or campaign,
                               testbed,
                               testbed_name=testbed_name,
                               run_result=act_result,
                               json_results=json_results,
                               exception=excep)


class ActsTestResults(object):
    """The packaged results of a test run."""
    acts_result_to_autotest = {
        'PASS': 'GOOD',
        'FAIL': 'FAIL',
        'UNKNOWN': 'WARN',
        'SKIP': 'ABORT'
    }

    def __init__(self,
                 name,
                 testbed,
                 testbed_name=None,
                 run_result=None,
                 json_results=None,
                 exception=None):
        """
        @param name: A name to identify the test run.
        @param testbed: The testbed that ran the test.
        @param testbed_name: The name the testbed was run with, if none the
                             default name of the testbed is used.
        @param run_result: The raw i/o result of the test run.
        @param json_results: Results loaded from the summary json output.
        @param exception: An exception that was thrown while running the test.
        """
        self.name = name
        self.run_result = run_result
        self.json_results = json_results
        self.exception = exception

        self.testbed = testbed
        if not testbed_name:
            # If no override is given get the name from the hostname.
            hostname = testbed.hostname
            if dnsname_mangler.is_ip_address(hostname):
                self.testbed_name = hostname
            else:
                self.testbed_name = hostname.split('.')[0]
        else:
            self.testbed_name = testbed_name

        self.reported_to = set()

    def log_output(self):
        """Logs the output of the test."""
        if self.run_result:
            logging.debug('ACTS Output:\n%s', self.run_result.stdout)

    def rethrow_exception(self):
        """Re-throws the exception thrown during the test."""
        if self.exception:
            raise self.exception

    def save_to(self, local_file):
        """Saves the test results to a file.

        Takes the json results and saves them to a json file on the drone.

        @param local_file: The file on the drone to save to.
        """
        try:
            os.makedirs(os.path.dirname(local_file))
        except IOError as e:
            if e.errno != errno.EEXIST:
                raise
        with open(local_file, mode='w') as fd:
            json.dump(self.json_results, fd)

    def upload_to_sponge(self, test):
        """Uploads the results to sponge.

        @param test: The autotest test object to upload.
        """
        self.report_to_autotest(test)
        summary_file = os.path.join(test.resultsdir, self.testbed_name,
                                    'latest/test_run_summary.json')
        self.save_to(summary_file)
        sponge_utils.upload_results_in_test(test, acts_summary=summary_file)

    def report_to_autotest(self, test):
        """Reports the results to an autotest test object.

        @param test: The autotest test object to report to. If this test object
                     has already recived our report then this call will be
                     ignored.
        """
        if test in self.reported_to:
            return

        if not 'Results' in self.json_results:
            return

        results = self.json_results['Results']
        for result in results:
            verdict = self.acts_result_to_autotest[result['Result']]
            details = result['Details']
            test.job.record(verdict, None, self.name, status=(details or ''))

        self.reported_to.add(test)