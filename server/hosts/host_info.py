# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import abc
import copy
import logging

import common
from autotest_lib.server.cros import provision


class HostInfo(object):
    """Holds label/attribute information about a host as understood by infra.

    This class is the source of truth of label / attribute information about a
    host for the test runner (autoserv) and the tests, *from the point of view
    of the infrastructure*.

    Typical usage:
        store = AfeHostInfoStore(...)
        host_info = store.get()
        update_somehow(host_info)
        store.commit(host_info)

    Besides the @property listed below, the following rw variables are part of
    the public API:
        labels: The list of labels for this host.
        attributes: The list of attributes for this host.
    """

    __slots__ = ['labels', 'attributes']

    def __init__(self, labels=None, attributes=None):
        """
        @param labels: (optional list) labels to set on the HostInfo.
        @param attributes: (optional dict) attributes to set on the HostInfo.
        """
        self.labels = labels if labels is not None else []
        self.attributes = attributes if attributes is not None else {}


    @property
    def build(self):
        """Retrieve the current build for the host.

        TODO(pprabhu) Make provision.py depend on this instead of the other way
        around.

        @returns The first build label for this host (if there are multiple).
                None if no build label is found.
        """
        for label_prefix in [provision.CROS_VERSION_PREFIX,
                            provision.ANDROID_BUILD_VERSION_PREFIX,
                            provision.TESTBED_BUILD_VERSION_PREFIX]:
            full_label_prefix = label_prefix + ':'
            build_labels = [label for label in self.labels
                            if label.startswith(full_label_prefix)]
            if build_labels:
                return build_labels[0][len(full_label_prefix):]
        return None


    def __str__(self):
        return ('HostInfo [Labels: %s, Attributes: %s'
                % (self.labels, self.attributes))


class StoreError(Exception):
    """Raised when a CachingHostInfoStore operation fails."""


class CachingHostInfoStore(object):
    """Abstract class to obtain and update host information from the infra.

    This class describes the API used to retrieve host information from the
    infrastructure. The actual, uncached implementation to obtain / update host
    information is delegated to the concrete store classes.

    We use two concrete stores:
        AfeHostInfoStore: Directly obtains/updates the host information from
                the AFE.
        LocalHostInfoStore: Obtains/updates the host information from a local
                file.
    An extra store is provided for unittests:
        InMemoryHostInfoStore: Just store labels / attributes in-memory.
    """

    __metaclass__ = abc.ABCMeta

    def __init__(self):
        self._private_cached_info = None


    def get(self, force_refresh=False):
        """Obtain (possibly cached) host information.

        @param force_refresh: If True, forces the cached HostInfo to be
                refreshed from the store.
        @returns: A HostInfo object.
        """
        if force_refresh:
            return self._get_uncached()

        # |_cached_info| access is costly, so do it only once.
        info = self._cached_info
        if info is None:
            return self._get_uncached()
        return info


    def commit(self, info):
        """Update host information in the infrastructure.

        @param info: A HostInfo object with the new information to set. You
                should obtain a HostInfo object using the |get| or
                |get_uncached| methods, update it as needed and then commit.
        """
        logging.debug('Committing HostInfo to store %s', self)
        try:
            self._commit_impl(info)
            self._cached_info = info
            logging.debug('HostInfo updated to: %s', info)
        except Exception:
            self._cached_info = None
            raise


    @abc.abstractmethod
    def _refresh_impl(self):
        """Actual implementation to refresh host_info from the store.

        Concrete stores must implement this function.
        @returns: A HostInfo object.
        """
        raise NotImplementedError


    @abc.abstractmethod
    def _commit_impl(self, host_info):
        """Actual implementation to commit host_info to the store.

        Concrete stores must implement this function.
        @param host_info: A HostInfo object.
        """
        raise NotImplementedError


    def _get_uncached(self):
        """Obtain freshly synced host information.

        @returns: A HostInfo object.
        """
        logging.debug('Refreshing HostInfo using store %s', self)
        logging.debug('Old host_info: %s', self._cached_info)
        try:
            info = self._refresh_impl()
            self._cached_info = info
        except Exception:
            self._cached_info = None
            raise

        logging.debug('New host_info: %s', info)
        return info


    @property
    def _cached_info(self):
        """Access the cached info, enforcing a deepcopy."""
        return copy.deepcopy(self._private_cached_info)


    @_cached_info.setter
    def _cached_info(self, info):
        """Update the cached info, enforcing a deepcopy.

        @param info: The new info to update from.
        """
        self._private_cached_info = copy.deepcopy(info)


class InMemoryHostInfoStore(CachingHostInfoStore):
    """A simple store that gives unittests direct access to backing data.

    Unittests can access the |info| attribute to obtain the backing HostInfo.
    """

    def __init__(self, info=None):
        """Seed object with initial data.

        @param info: Initial backing HostInfo object.
        """
        super(InMemoryHostInfoStore, self).__init__()
        self.info = info if info is not None else HostInfo()


    def _refresh_impl(self):
        """Return a copy of the private HostInfo."""
        return copy.deepcopy(self.info)


    def _commit_impl(self, info):
        """Copy HostInfo data to in-memory store.

        @param info: The HostInfo object to commit.
        """
        self.info = copy.deepcopy(info)