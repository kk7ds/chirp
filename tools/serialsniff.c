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

#define STREQ(a,b) (strcmp(a,b) == 0)

struct path {
	int fd;
	char path[1024];
	char name[1024];
	int rawlog_fd;
};

void hexdump(char *buf, int len, FILE *dest)
{
	int i;
	int j;

	for (i = 0; i < len; i += 8) {
		for (j = i; j < i + 8; j++) {
			if ((j % 4) == 0)
				fprintf(dest, " ");

			if (j < len)
				fprintf(dest, "%02x", buf[j] & 0xFF);
			else
				fprintf(dest, "--");
		}

		fprintf(dest, "   ");

		for (j = i; j < i + 8; j++) {
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
	path->fd = posix_openpt(O_RDWR);
	if (path->fd < 0) {
		perror("posix_openpt");
		return false;
	}

	grantpt(path->fd);
	unlockpt(path->fd);

	ptsname_r(path->fd, path->path, sizeof(path->path));
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

static bool open_path(const char *opt, struct path *path)
{
	if (STREQ(opt, "pty"))
		return open_pty(path);
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
	       "  -A,--pathA=DEV   Path to device A (or 'pty')\n"
	       "  -B,--pathB=DEV   Path to device B (or 'pty')\n"
	       "     --logA=FILE   Log pathA (raw) to FILE\n"
	       "     --logB=FILE   Log pathB (raw) to FILE\n"
	       "     --nameA=NAME  Set pathA name to NAME\n"
	       "     --nameB=NAME  Set pathB name to NAME\n"
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

	while (1) {
		int optind;
		static struct option lopts[] = {
			{"pathA", 1, 0, 'A'},
			{"pathB", 1, 0, 'B'},
			{"logA",  1, 0, 1 },
			{"logB",  1, 0, 2 },
			{"nameA", 1, 0, 3 },
			{"nameB", 1, 0, 4 },
			{0, 0, 0, 0}
		};

		c = getopt_long(argc, argv, "A:B:l:",
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
