# Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import fcntl
import logging
import os
import pyudev
import random
import re
import socket
import struct
import subprocess
import time

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import flimflam_test_path


class EthernetDongle(object):
    """ Used for definining the desired module expect states. """

    def __init__(self, expect_speed='100', expect_duplex='full'):
        # Expected values for parameters.
        self.expected_parameters = {
            'ifconfig_status': 0,
            'duplex': expect_duplex,
            'speed': expect_speed,
            'mac_address': None,
            'ipaddress': None,
        }

    def GetParam(self, parameter):
        return self.expected_parameters[parameter]

class network_EthernetStressPlug(test.test):
    version = 1

    def initialize(self):
        """ Determines and defines the bus information and interface info. """

        def get_net_device_path(device='eth0'):
            """ Uses udev to get the path of the desired internet device. """
            net_list = pyudev.Context().list_devices(subsystem='net')
            for dev in net_list:
                if device in dev.sys_path:
                    # Support usb devices where the device path should match
                    # something of the form
                    # /sys/devices/pci.*/0000.*/usb.*/.*.
                    net_path = re.search('(/sys/devices/pci[^/]*/0000[^/]*/'
                                         'usb[^/]*/[^/]*)', dev.sys_path)
                    if net_path:
                        return net_path.groups()[0]

                    # On some system such as Snow, usb is not on pci bus
                    net_path = re.search('(/sys/devices/.*/usb[^/].*/.*/'
                                         'net/[^/]*)', dev.sys_path)
                    if net_path:
                        return net_path.groups()[0]

                    # Support onboard Ethernet without usb dongle where the
                    # device path should match something of the form
                    # /sys/device/platform/.*/net/.*
                    net_path = re.search('(/sys/devices/platform/.*/net/[^/]*)',
                                         dev.sys_path)
                    if net_path:
                        return net_path.groups()[0]

            raise error.TestError('%s was not found or could not be '
                                  'for this test.' % device)

        self.interface = 'eth0'
        self.eth_syspath = get_net_device_path(self.interface)

        # Stores the status of the most recently run iteration.
        self.test_status = {
            'ipaddress': None,
            'eth_state': None,
            'reason': None,
            'last_wait': 0
        }

        self.secs_before_warning = 10

        # Represents the current number of instances in which ethernet
        # took longer than dhcp_warning_level to come up.
        self.warning_count = 0

        # The percentage of test warnings before we fail the test.
        self.warning_threshold = .25

    def GetIPAddress(self):
        """ Obtains the ipaddress of the interface. """
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            return socket.inet_ntoa(fcntl.ioctl(
                   s.fileno(), 0x8915,  # SIOCGIFADDR
                   struct.pack('256s', self.interface[:15]))[20:24])
        except:
            return None

    def GetEthernetStatus(self):
        """
        Updates self.test_status with the status of the ethernet interface.

        Returns:
            True if the ethernet device is up.  False otherwise.
        """

        def ReadEthVal(param):
            """ Reads the network parameters of the interface. """
            eth_path = os.path.join('/', 'sys', 'class', 'net', self.interface,
                                    param)
            val = None
            try:
                fp = open(eth_path)
                val = fp.readline().strip()
                fp.close()
            except:
                pass
            return val

        eth_out = self.ParseEthTool()
        ethernet_status = {
            'ifconfig_status': utils.system('ifconfig %s' % self.interface,
                                            ignore_status=True),
            'duplex': eth_out.get('Duplex'),
            'speed': eth_out.get('Speed'),
            'mac_address': ReadEthVal('address'),
            'ipaddress': self.GetIPAddress()
        }

        self.test_status['ipaddress'] = ethernet_status['ipaddress']

        for param, val in ethernet_status.iteritems():
            if self.dongle.GetParam(param) is None:
                # For parameters with expected values none, we check the
                # existence of a value.
                if not bool(val):
                    self.test_status['eth_state'] = False
                    self.test_status['reason'] = '%s is not ready: %s == %s' \
                                                 % (self.interface, param, val)
                    return False
            else:
                if val != self.dongle.GetParam(param):
                    self.test_status['eth_state'] = False
                    self.test_status['reason'] = '%s is not ready. (%s)\n' \
                                                 "  Expected: '%s'\n" \
                                                 "  Received: '%s'" \
                                                 % (self.interface, param,
                                                 self.dongle.GetParam(param),
                                                 val)
                    return False

        self.test_status['eth_state'] = True
        self.test_status['reason'] = None
        return True

    def _PowerEthernet(self, power=1):
        """ Sends command to change the power state of ethernet.
        Args:
          power: 0 to unplug, 1 to plug.
        """
        # "authorized" file will disable USB port and in some cases power
        # off the port.
        if os.path.exists(os.path.join(self.eth_syspath, 'authorized')):
            fp = open(os.path.join(self.eth_syspath, 'authorized'), 'w')
            fp.write('%d' % power)
            fp.close()
        # Linux supports standard ioctl to configures network devices by seting
        # or getting a 16-bit short number flags.
        # The LSB is IFF_UP, which controls that interface is running or not.
        elif os.path.exists(os.path.join(self.eth_syspath, 'flags')):
            fp = open(os.path.join(self.eth_syspath, 'flags'), 'w')
            fp.write('0x1003' if power else '0x1002')
            fp.close()
        # else use ifconfig eth0 up/down to switch
        else:
            logging.warning('plug/unplug event control not found. '
                            'Use ifconfig %s %s instead' %
                         (self.interface, 'up' if power else 'down'))
            result = subprocess.check_call(['ifconfig', self.interface,
                                            'up' if power else 'down'])
            if result:
                raise error.TestError('Fail to change the power state of %s' %
                                      self.interface)

    def TestPowerEthernet(self, power=1, timeout=45):
        """ Tests enabling or disabling the ethernet.
        Args:
            power: 0 to unplug, 1 to plug.
            timeout: Indicates approximately the number of seconds to timeout
                     how long we should check for the success of the ethernet
                     state change.

        Returns:
            The time in seconds required for device to transfer to the desired
            state.

        Raises:
            error.TestFail if the ethernet status is not in the desired state.
        """

        start_time = time.time()
        end_time = start_time + timeout

        status_str = ['off', 'on']
        self._PowerEthernet(power)

        while time.time() < end_time:
            status = self.GetEthernetStatus()

            # If ethernet is enabled and it has an IP, or if ethernet
            # is disabled and does not have an IP, we are in the desired state.
            # Return the number of "seconds" for this to happen.
            # (translated to an approximation of the number of seconds)
            if (power and status and \
                self.test_status['ipaddress'] is not None) or \
                (not power and not status and \
                self.test_status['ipaddress'] is None):
                return time.time()-start_time

            time.sleep(1)

        else:
            logging.debug(self.test_status['reason'])
            raise error.TestFail('ERROR: %s IP is %s despite setting power to '
                                 '%s after %.2f seconds.' %
                                 (self.interface, self.test_status['ipaddress'],
                                 status_str[power],
                                 self.test_status['last_wait']))

    def RandSleep(self, min_sleep, max_sleep):
        """ Sleeps for a random duration.

        Args:
            min_sleep: Minimum sleep parameter in miliseconds.
            max_sleep: Maximum sleep parameter in miliseconds.
        """
        duration = random.randint(min_sleep, max_sleep)/1000.0
        self.test_status['last_wait'] = duration
        time.sleep(duration)

    def _ParseEthTool_LinkModes(self, line):
        """ Parses Ethtool Link Mode Entries.

        Inputs:
            line: Space separated string of link modes that have the format
                  (\d+)baseT/(Half|Full) (eg. 100baseT/Full).

        Outputs:
            List of dictionaries where each dictionary has the format
            { 'Speed': '<speed>', 'Duplex': '<duplex>' }
        """
        parameters = []
        for speed_to_parse in line.split():
            speed_duplex = speed_to_parse.split('/')
            parameters.append(
                {
                    'Speed': re.search('(\d*)', speed_duplex[0]).groups()[0],
                    'Duplex': speed_duplex[1],
                }
            )
        return parameters

    def ParseEthTool(self):
        """
        Parses the output of Ethtools into a dictionary and returns
        the dictionary with some cleanup in the below areas:
            Speed: Remove the unit of speed.
            Supported link modes: Construct a list of dictionaries.
                                  The list is ordered (relying on ethtool)
                                  and each of the dictionaries contains a Speed
                                  kvp and a Duplex kvp.
            Advertised link modes: Same as 'Supported link modes'.

        Sample Ethtool Output:
            Supported ports: [ TP MII ]
            Supported link modes:   10baseT/Half 10baseT/Full
                                    100baseT/Half 100baseT/Full
                                    1000baseT/Half 1000baseT/Full
            Supports auto-negotiation: Yes
            Advertised link modes:  10baseT/Half 10baseT/Full
                                    100baseT/Half 100baseT/Full
                                    1000baseT/Full
            Advertised auto-negotiation: Yes
            Speed: 1000Mb/s
            Duplex: Full
            Port: MII
            PHYAD: 2
            Transceiver: internal
            Auto-negotiation: on
            Supports Wake-on: pg
            Wake-on: d
            Current message level: 0x00000007 (7)
            Link detected: yes

        Returns:
          A dictionary representation of the above ethtool output, or an empty
          dictionary if no ethernet dongle is present.
          Eg.
            {
              'Supported ports': '[ TP MII ]',
              'Supported link modes': [{'Speed': '10', 'Duplex': 'Half'},
                                       {...},
                                       {'Speed': '1000', 'Duplex': 'Full'}],
              'Supports auto-negotiation: 'Yes',
              'Advertised link modes': [{'Speed': '10', 'Duplex': 'Half'},
                                        {...},
                                        {'Speed': '1000', 'Duplex': 'Full'}],
              'Advertised auto-negotiation': 'Yes'
              'Speed': '1000',
              'Duplex': 'Full',
              'Port': 'MII',
              'PHYAD': '2',
              'Transceiver': 'internal',
              'Auto-negotiation': 'on',
              'Supports Wake-on': 'pg',
              'Wake-on': 'd',
              'Current message level': '0x00000007 (7)',
              'Link detected': 'yes',
            }
        """
        parameters = {}
        ethtool_out = os.popen('ethtool %s' % self.interface).read().split('\n')
        if 'No data available' in ethtool_out:
            return parameters

        # For multiline entries, keep track of the key they belong to.
        current_key = ''
        for line in ethtool_out:
            current_line = line.strip().partition(':')
            if current_line[1] == ':':
                current_key = current_line[0]

                # Assumes speed does not span more than one line.
                # Also assigns empty string if speed field
                # is not available.
                if current_key == 'Speed':
                    speed = re.search('^\s*(\d*)', current_line[2])
                    parameters[current_key] = ''
                    if speed:
                        parameters[current_key] = speed.groups()[0]
                elif (current_key == 'Supported link modes' or
                      current_key == 'Advertised link modes'):
                    parameters[current_key] = []
                    parameters[current_key] += \
                        self._ParseEthTool_LinkModes(current_line[2])
                else:
                    parameters[current_key] = current_line[2].strip()
            else:
              if (current_key == 'Supported link modes' or
                  current_key == 'Advertised link modes'):
                  parameters[current_key] += \
                      self._ParseEthTool_LinkModes(current_line[0])
              else:
                  parameters[current_key]+=current_line[0].strip()

        return parameters

    def GetDongle(self):
        """ Returns the ethernet dongle object associated with what's connected.

        Dongle uniqueness is retrieved from the 'product' file that is
        associated with each usb dongle in
        /sys/devices/pci.*/0000.*/usb.*/.*-.*/product.  The correct
        dongle object is determined and returned.

        Returns:
          Object of type EthernetDongle.

        Raises:
          error.TestFail if ethernet dongle is not found.
        """
        ethtool_dict = self.ParseEthTool()

        if not ethtool_dict:
            raise error.TestFail('Unable to parse ethtool output for %s.' %
                                 self.interface)

        # Ethtool output is ordered in terms of speed so this obtains the
        # fastest speed supported by dongle.
        max_link = ethtool_dict['Supported link modes'][-1]

        return EthernetDongle(expect_speed=max_link['Speed'],
                              expect_duplex=max_link['Duplex'])

    def run_once(self, num_iterations=1):
        try:
            self.dongle = self.GetDongle()

            #Sleep for a random duration between .5 and 2 seconds
            #for unplug and plug scenarios.
            for i in range(num_iterations):
                logging.debug('Iteration: %d' % i)
                if self.TestPowerEthernet(power=0) > self.secs_before_warning:
                    self.warning_count+=1

                self.RandSleep(500, 2000)
                if self.TestPowerEthernet(power=1) > self.secs_before_warning:
                    self.warning_count+=1

                self.RandSleep(500, 2000)

                if self.warning_count > num_iterations * self.warning_threshold:
                    raise error.TestFail('ERROR: %.2f%% of total runs (%d) '
                                         'took longer than %d seconds for '
                                         'ethernet to come up.' %
                                         (self.warning_threshold*100,
                                          num_iterations,
                                          self.secs_before_warning))

        except Exception as e:
            self._PowerEthernet(1)
            raise e
