LOCALES = en_US pl
MOFILES = $(patsubst %,%/LC_MESSAGES/CHIRP.mo,$(LOCALES))

COPY="Dan Smith <dsmith@danplanet.com>"
PKG=CHIRP
XGT_OPTS=--copyright-holder=$(COPY) --package-name=$(PKG)

all: $(MOFILES)

clean:
	rm -f $(MOFILES) *~
	for mo in $(MOFILES); do rmdir -p `dirname $$mo`; done

chirpui.pot:
	/usr/bin/find ../chirpui -name '*.py' > .files
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
