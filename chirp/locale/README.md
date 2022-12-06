# Prerequisites

You need `make`, `xgettext`, `msgmerge`, and `msginit` to do this. That might
be hard on Windows, but on a Linux machine the `gettext` package (also
available in `brew` on macos) should be enough.

# Add a language

To add a new language for locale "xx", do:

```
  $ make xx.po
```

Edit the xx.po file and then commit it to the tree.

# Update a language

To update a language, run:

```
  $ make clean
  $ make
```

which will merge new strings into the .po files. Edit your po file and
commit it (and only that file) to the tree.
