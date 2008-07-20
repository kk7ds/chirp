#!/bin/bash -x

OUTPUT=$(echo "c:\\cygwin\\${1}/" | sed 's/\//\\/'g)

VERSION=$(cat build/version)
ZIP=${OUTPUT}chirp-$VERSION-win32.zip
IST=${OUTPUT}chirp-$VERSION-installer.exe
LOG=d-rats_build.log

export GTK_BASEPATH='C:\GTK'
export PATH=$PATH:/cygdrive/c/GTK/bin

shift

build_win32() {
	echo Building Win32 executable...
	/cygdrive/c/Python25/python.exe setup.py py2exe >> $LOG
	if [ $? -ne 0 ]; then
		echo "Build failed"
		exit
	fi
}

copy_lib() {
	echo Copying GTK lib, etc, share...
	cp -r /cygdrive/c/GTK/{lib,etc,share} dist
}

copy_data() {
	list="COPYING"
	for i in $list; do
		cp -v $i $dist >> $LOG
	done
}

make_zip() {
	echo Making ZIP archive...
	(cd dist && zip -9 -r $ZIP .) >> $LOG
}

make_installer() {
	echo Making Installer...
	cat > d-rats.nsi <<EOF
Name "D-RATS Installer"
OutFile "${IST}"
InstallDir \$PROGRAMFILES\D-RATS
DirText "This will install D-RATS v$VERSION"
Icon d-rats2.ico
SetCompressor 'lzma'
Section ""
  InitPluginsDir
  SetOutPath "\$INSTDIR"
  File /r 'dist\*.*'
  CreateDirectory "\$SMPROGRAMS\D-RATS"
  CreateShortCut "\$SMPROGRAMS\D-RATS\D-RATS Communications Tool.lnk" "\$INSTDIR\d-rats.exe"
  CreateShortCut "\$SMPROGRAMS\D-RATS\D-RATS Repeater.lnk" "\$INSTDIR\repeater.exe"
  CreateShortCut "\$SMPROGRAMS\D-RATS\D-RATS Map Downloader.lnk" "\$INSTDIR\mapdownloader.exe"
  CreateDirectory "\$APPDATA\D-RATS\Form_Templates"
  CopyFiles \$INSTDIR\forms\*.* "\$APPDATA\D-RATS\Form_Templates"
SectionEnd
EOF
	unix2dos d-rats.nsi
	/cygdrive/c/Program\ Files/NSIS/makensis d-rats.nsi
}

rm -f $LOG

copy_data
build_win32
copy_lib

if [ "$1" = "-z" ]; then
	make_zip
elif [ "$1" = "-i" ]; then
	make_installer
elif [ -z "$1" ]; then
	make_zip
	#make_installer
fi
	
