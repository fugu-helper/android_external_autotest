// Copyright (c) 2012 The Chromium OS Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cerrno>
#include <cstdlib>
#include <cstring>
#include <iostream>

int recbomb(int n);
void PrepareBelow(int argc, char *argv[]);
extern int DefeatTailOptimizationForCrasher();
int DefeatTailOptimizationForBomb() {
  return 0;
}

int main(int argc, char *argv[]) {
  PrepareBelow(argc, argv);
  return recbomb(16) + DefeatTailOptimizationForCrasher();
}

bool SendPid(const char *socket_path);

using std::cerr;

// Prepare for doing the crash, but do it below main so that main's
// line numbers remain stable.
void PrepareBelow(int argc, char *argv[]) {
  cerr << "pid=" << getpid() << '\n';
  if (argc == 2 && strcmp(argv[1], "--nocrash") == 0) {
    cerr << "Doing normal exit\n";
    exit(0);
  }
  if (argc == 3 && strcmp(argv[1], "--sendpid") == 0) {
    if (!SendPid(argv[2]))
      exit(0);
  }
  cerr << "Crashing as requested.\n";
}

// Used when the crasher runs in a different PID namespace than the test. A PID
// sent over a Unix domain socket to a process in a different PID namespace is
// converted to that PID namespace.
bool SendPid(const char *socket_path) {
  struct Socket {
    Socket(): fd(socket(AF_UNIX, SOCK_DGRAM, 0)) {}
    ~Socket() { if (fd != -1) close(fd); }
    int fd;
  } sock;

  if (sock.fd == -1) {
    cerr << "socket() failed: " << strerror(errno) << '\n';
    return false;
  }

  sockaddr_un address = { AF_UNIX };
  strncpy(address.sun_path, socket_path, sizeof(address.sun_path) - 1);
  sockaddr *address_ptr = reinterpret_cast<sockaddr *>(&address);
  if (connect(sock.fd, address_ptr, sizeof(address)) == -1) {
    cerr << "connect() failed: " << strerror(errno) << '\n';
    return false;
  }

  char zero = '\0';
  iovec data = { &zero, 1 };
  msghdr msg = { NULL, 0, &data, 1 };

  if (sendmsg(sock.fd, &msg, 0) == -1) {
    cerr << "sendmsg() failed: " << strerror(errno) << '\n';
    return false;
  }

  return true;
}
