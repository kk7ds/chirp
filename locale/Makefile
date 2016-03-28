LOCALES = en_US pl it nl de hu ru pt_BR fr uk_UA es_ES
MOFILES = $(patsubst %,%/LC_MESSAGES/CHIRP.mo,$(LOCALES))

COPY="Dan Smith <dsmith@danplanet.com>"
PKG=CHIRP
XGT_OPTS=--copyright-holder=$(COPY) --package-name=$(PKG)

all: $(MOFILES)

clean:
	rm -f $(MOFILES) *~ *.orig
	find . -name '*.mo' -exec rm -f "{}" \;
	find * -depth -type d -exec rmdir "{}" \;

chirpui.pot:
	/usr/bin/find ../chirp/ui -name '*.py' > .files
	xgettext -L Python -k_ -o chirpui.pot -f .files $(XGT_OPTS)

%.po: chirpui.pot
	if [ -f $@ ]; then                                \
	msgmerge -U $@ chirpui.pot;                       \
	else                                              \
	msginit --input=chirpui.pot --locale=$(@:%.po=%); \
	fi

%/LC_MESSAGES/CHIRP.mo: %.po
	mkdir -p $(shell dirname $@)
	msgfmt --output-file=$@ $^
