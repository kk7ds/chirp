#
#
# Makefile for serialsniff
#
# Author: IT2 Stuart Blake Tener, USNR (N3GWG)
#
# Version 1.00
#
#	This makefile checks to see if we are running under the OS "Darwin"
#	and passes the proper macro flag ("MACOS") if we are.
#
#	Incidentally, it is noteworthy that MacOS (Darwin) is not the only
#	operating system which is deficient some of the library routines
#	MacOS is currently defficient. Thus, it is instructive that other
#	operating systems names might need to be added for compilation to
#	become occurring in their environments.
#
#

ifndef SYSNAME
	SYSNAME := $(shell uname -s)
	ifeq ($(SYSNAME),Darwin)
		MYFLAGS	:= "-DMACOS"
		REMOVE	:= srm -vrfz
	else
		REMOVE	:= rm -rf
	endif
endif

serialsniff: serialsniff.c
	$(CC) $? -o $@ $(LDFLAGS) $(CFLAGS) $(MYFLAGS)

clean:
	$(REMOVE)  serialsniff *~ *.o *.bak core tags shar a.out

