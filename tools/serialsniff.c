/*
 *
 * Copyright 2008 Dan Smith <dsmith@danplanet.com>
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

/*
 *
 * Modifications made by:
 *	Stuart Blake Tener, N3GWG
 *	Email:		<teners@bh90210.net>
 *	Mobile phone:	+1 (310) 358-0202
 *
 * 02 MAR 2009 - Version 1.01
 *
 *		Logic was changed to use "ptsname" instead of "ptsname_r"
 *		in pursuance of provisioning greater compatibility with other
 *		Unix variants and Open Standards Unix flavors which have not
 *		otherwise implemented the "ptsname_r" system call.
 *		Changes developed and tested under MacOS 10.5.6 (Leopard)
 *
 *		Added "--quiescent" switch, which when used on the command
 *		line prevents the printing of "Timeout" and count notices
 *		on the console.
 *		Changes developed and tested under MacOS 10.5.6 (Leopard)
 *
 *		Added program title and version tagline, printed when the
 *		software is first started.
 *
 * 03 MAR 2009 - Version 1.02
 *
 *		Added "--digits" switch, which when used on the command
 *		line allows for setting the number of hex digits print per
 *		line.
 *
 *		Added code to allow "-q" shorthand for "quiescent mode".
 *
 *		Changes were made to add "#ifdef" statements so that only code
 *		appropriate to MacOS would be compiled if a "#define MACOS" is
 *		defined early within the source code.
 *
 *		Cleaned up comments in the source for my new source code.
 *
 *		Changes developed and tested under MacOS 10.5.6 (Leopard)
 *
 */

#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <fcntl.h>
#include <sys/select.h>
#include <sys/time.h>
#include <sys/types.h>
#include <unistd.h>
#include <string.h>
#include <signal.h>
#include <getopt.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <arpa/inet.h>

#define STREQ(a,b) (strcmp(a,b) == 0)

char	*version = "1.02 (03 MAR 2009)";
int	quiescent = 0;
int	total_hex = 20;

struct path {
	int fd;
	char path[1024];
	char name[1024];
	int rawlog_fd;
};

void hexdump(char *buf, int len, FILE *dest)
{
	/*
	 * In precedence to the modification of this procedure to support the
	 * variable size hexadecimal output, the total bytes output was fixed
	 * to be a length of 8.
	 *
	 * The amendment of this procedure to support the "total_hex" variable
	 * allows for the user to pass a command line argument instantiating a
	 * desired number of hexadecimal bytes (and their ASCII equivalent) to
	 * be displayed.
	 *
	 */

	int i;
	int j;

	for (i = 0; i < len; i += total_hex) {
		for (j = i; j < i + total_hex; j++) {
			if ((j % 4) == 0)
				fprintf(dest, " ");

			if (j < len)
				fprintf(dest, "%02x", buf[j] & 0xFF);
			else
				fprintf(dest, "--");
		}

		fprintf(dest, "   ");

		for (j = i; j < i + total_hex; j++) {
			if ((j % 4) == 0)
				fprintf(dest, " ");

			if (j > len)
				fprintf(dest, ".");
			else if ((buf[j] > ' ') && (buf[j] < '~'))
				fprintf(dest, "%c", buf[j]);
			else
				fprintf(dest, ".");
		}

		fprintf(dest, "\n");
	}
}

int saferead(int fd, char *buf, int len)
{
	struct itimerval val;
	int ret;
	int count = 0;

	memset(&val, 0, sizeof(val));
	val.it_value.tv_usec = 50000;
	setitimer(ITIMER_REAL, &val, NULL);

	while (count < len) {
		getitimer(ITIMER_REAL, &val);
		if ((val.it_value.tv_sec == 0) &&
		    (val.it_value.tv_usec == 0)) {
			if (!quiescent)
				printf("Timeout\n");
			break;
		}

		ret = read(fd, &(buf[count]), len - count);
		if (ret > 0)
			count += ret;
	}

	return count;
}

void proxy(struct path *pathA, struct path *pathB)
{
	fd_set rfds;
	int ret;
	struct timeval tv;

	while (1) {
		int count = 0;
		int ret;
		char buf[4096];

		FD_ZERO(&rfds);

		FD_SET(pathA->fd, &rfds);
		FD_SET(pathB->fd, &rfds);

		ret = select(30, &rfds, NULL, NULL, NULL);
		if (ret == -1) {
			perror("select");
			break;
		}

		if (FD_ISSET(pathA->fd, &rfds)) {
			count = saferead(pathA->fd, buf, sizeof(buf));
			if (count < 0)
				break;

			ret = write(pathB->fd, buf, count);
			if (ret != count)
				printf("Failed to write %i (%i)\n", count, ret);
			if (!quiescent)
				printf("%s %i:\n", pathA->name, count);
			hexdump(buf, count, stdout);

			if (pathA->rawlog_fd >= 0) {
				ret = write(pathA->rawlog_fd, buf, count);
				if (ret != count)
					printf("Failed to write %i to %s log",
					       count,
					       pathA->name);
			}

		}

		if (FD_ISSET(pathB->fd, &rfds)) {
			count = saferead(pathB->fd, buf, sizeof(buf));
			if (count < 0)
				break;

			ret = write(pathA->fd, buf, count);
			if (ret != count)
				printf("Failed to write %i (%i)\n", count, ret);
			if (!quiescent)
				printf("%s %i:\n", pathB->name, count);
			hexdump(buf, count, stdout);

			if (pathB->rawlog_fd >= 0) {
				ret = write(pathB->rawlog_fd, buf, count);
				if (ret != count)
					printf("Failed to write %i to %s log",
					       count,
					       pathB->name);
			}
		}
	}
}

static bool open_pty(struct path *path)
{
#ifdef MACOS
	char	*ptsname_path;
#endif

	path->fd = posix_openpt(O_RDWR);
	if (path->fd < 0) {
		perror("posix_openpt");
		return false;
	}

	grantpt(path->fd);
	unlockpt(path->fd);

#ifdef MACOS
	ptsname_path = ptsname(path->fd);
	strncpy(path->path,ptsname_path,sizeof(path->path) - 1);
#else
	ptsname_r(path->fd, path->path, sizeof(path->path));
#endif

	fprintf(stderr, "%s\n", path->path);

	return true;
}

static bool open_serial(const char *serpath, struct path *path)
{
	path->fd = open(serpath, O_RDWR);
	if (path->fd < 0)
		perror(serpath);

	strncpy(path->path, serpath, sizeof(path->path));

	return path->fd >= 0;
}

static bool open_socket(const char *foo, struct path *path)
{
	int lfd;
	struct sockaddr_in srv;
	struct sockaddr_in cli;
	unsigned int cli_len = sizeof(cli);
	int optval = 1;

	lfd = socket(AF_INET, SOCK_STREAM, 0);
	if (lfd < 0) {
		perror("socket");
		return false;
	}

        srv.sin_family = AF_INET;
        srv.sin_port = htons(2000);
        srv.sin_addr.s_addr = INADDR_ANY;

        setsockopt(lfd, SOL_SOCKET, SO_REUSEADDR, &optval, sizeof(optval));

        if (bind(lfd, (struct sockaddr *)&srv, sizeof(srv)) < 0) {
                perror("bind");
                return false;
        }

        if (listen(lfd, 1) < 0) {
                perror("listen");
		return false;
        }

	printf("Waiting...\n");

	path->fd = accept(lfd, (struct sockaddr *)&cli, &cli_len);
	if (path->fd < 0) {
		perror("accept");
		return false;
	}

	printf("Accepted socket client\n");

	strcpy(path->path, "SOCKET");

	return true;
}

static bool open_path(const char *opt, struct path *path)
{
	if (STREQ(opt, "pty"))
		return open_pty(path);
	else if (STREQ(opt, "listen"))
		return open_socket(opt, path);
	else
		return open_serial(opt, path);
}

static bool open_log(const char *filename, struct path *path)
{
	path->rawlog_fd = open(filename, O_WRONLY | O_CREAT, 0644);
	if (path->rawlog_fd < 0)
		perror(filename);

	return path->rawlog_fd >= 0;
}

static void usage()
{
	printf("Usage:\n"
	       "serialsniff [OPTIONS]\n"
	       "Where OPTIONS are:\n"
	       "\n"
	       "      -A,--pathA=DEV 	Path to device A (or 'pty')\n"
	       "      -B,--pathB=DEV 	Path to device B (or 'pty')\n"
	       "         --logA=FILE 	Log pathA (raw) to FILE\n"
	       "         --logB=FILE 	Log pathB (raw) to FILE\n"
	       "         --nameA=NAME	Set pathA name to NAME\n"
	       "         --nameB=NAME	Set pathB name to NAME\n"
	       "  --q,-q,--quiescent	Run in quiescent mode\n"
	       "  --d,-d,--digits	Number of hex digits to print in one line\n\n"
	       "  --d=nn or -d nn or --digits nn\n"
	       "\n"
	       );
}

int main(int argc, char **argv)
{

	struct sigaction sa;

	struct path pathA;
	struct path pathB;

	int c;

	strcpy(pathA.name, "A");
	strcpy(pathB.name, "B");
	pathA.fd = pathA.rawlog_fd = -1;
	pathB.fd = pathB.rawlog_fd = -1;

	printf("\nserialsniff - Version %s\n\n",version);

	while (1) {
		int optind;
		static struct option lopts[] = {
			{"pathA", 1, 0, 'A'},
			{"pathB", 1, 0, 'B'},
			{"logA",  1, 0, 1 },
			{"logB",  1, 0, 2 },
			{"nameA", 1, 0, 3 },
			{"nameB", 1, 0, 4 },
			{"quiescent", 0, 0, 'q' },
			{"digits", 1, 0, 'd'},
			{0, 0, 0, 0}
		};

		c = getopt_long(argc, argv, "A:B:d:l:q",
				lopts, &optind);
		if (c == -1)
			break;

		switch (c) {

		case 'A':
			if (!open_path(optarg, &pathA))
				return 1;
			break;

		case 'B':
			if (!open_path(optarg, &pathB))
				return 2;
			break;

		case 1:
			if (!open_log(optarg, &pathA))
				return 3;
			break;

		case 2:
			if (!open_log(optarg, &pathB))
				return 4;
			break;

		case 3:
			strncpy(pathA.name, optarg, sizeof(pathA.name));
			break;

		case 4:
			strncpy(pathB.name, optarg, sizeof(pathB.name));
			break;

		case 'q':
			quiescent = 1;
			break;

		case 'd':
			total_hex=atoi(optarg);
			break;

		case '?':
			return 3;
		}
	}

	memset(&sa, 0, sizeof(sa));
	sa.sa_handler = SIG_IGN;
	sigaction(SIGALRM, &sa, NULL);

	if ((pathA.fd < 0) || (pathB.fd < 0)) {
		usage();
		return -1;
	}

	proxy(&pathA, &pathB);

	return 0;
}
