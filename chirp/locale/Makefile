POFILES = $(shell ls *.po)
MOFILES = $(patsubst %.po,%/LC_MESSAGES/CHIRP.mo,$(POFILES))
SHELL = bash

COPY="Dan Smith <chirp@f.danplanet.com>"
PKG=CHIRP
XGT_OPTS=--copyright-holder=$(COPY) --package-name=$(PKG)

.PHONY: all

all: chirpui.pot $(MOFILES)

clean:
	rm -f $(MOFILES) *~ *.orig chirpui.pot
	find . -name '*.mo' -exec rm -f "{}" \;
	find * -depth -type d -exec rmdir "{}" \;

chirpui.pot:
	xgettext -s -L Python -k_ -o chirpui.pot --from-code=iso-8859-15 -f <( \
	  /usr/bin/find .. -name '*.py') $(XGT_OPTS)

%.po: chirpui.pot
	if [ -f $@ ]; then                                \
	msgmerge --no-wrap -sU $@ chirpui.pot;            \
	else                                              \
	msginit --input=chirpui.pot --locale=$(@:%.po=%); \
	fi

%/LC_MESSAGES/CHIRP.mo: %.po
	mkdir -p $(shell dirname $@)
	msgfmt --output-file=$@ $^
