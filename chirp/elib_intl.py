# -*- coding: utf-8 -*-
#
# Copyright © 2007-2010 Dieter Verfaillie <dieterv@optionexplicit.be>
#
# This file is part of elib.intl.
#
# elib.intl is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# elib.intl is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with elib.intl. If not, see <http://www.gnu.org/licenses/>.


'''
The elib.intl module provides enhanced internationalization (I18N)
services for your Python modules and applications.

elib.intl wraps Python's :func:`gettext` functionality and adds the
following on Microsoft Windows systems:

 - automatic detection of the current screen language (not necessarily
   the same as the installation language) provided by MUI packs,
 - makes sure internationalized C libraries which internally invoke
   gettext() or dcgettext() can properly locate their message catalogs.
   This fixes a known limitation in gettext's Windows support when using
   eg. gtk.builder or gtk.glade.

See http://www.gnu.org/software/gettext/FAQ.html#windows_setenv for more
information.

The elib.intl module defines the following functions:
'''

import os
import sys
import locale
import gettext

from logging import getLogger

__all__ = ['install', 'install_module']
__version__ = '0.0.3'
__docformat__ = 'restructuredtext'

logger = getLogger('elib.intl')


def _isofromlcid(lcid):
    '''
    :param lcid: Microsoft Windows LCID
    :returns: the ISO 639-1 language code for a given lcid. If there is no
              ISO 639-1 language code assigned to the language specified
              by lcid, the ISO 639-2 language code is returned. If the
              language specified by lcid is unknown in the ISO 639-x
              database, None is returned.

    More information can be found on the following websites:
        - List of ISO 639-1 and ISO 639-2 language codes:
          http://www.loc.gov/standards/iso639-2/
        - List of known lcid's:
          http://www.microsoft.com/globaldev/reference/lcid-all.mspx
        - List of known MUI packs:
          http://www.microsoft.com/globaldev/reference/win2k/setup/Langid.mspx
    '''
    mapping = {1078:    'af',   # frikaans - South Africa
               1052:    'sq',   # lbanian - Albania
               1118:    'am',   # mharic - Ethiopia
               1025:    'ar',   # rabic - Saudi Arabia
               5121:    'ar',   # rabic - Algeria
               15361:   'ar',   # rabic - Bahrain
               3073:    'ar',   # rabic - Egypt
               2049:    'ar',   # rabic - Iraq
               11265:   'ar',   # rabic - Jordan
               13313:   'ar',   # rabic - Kuwait
               12289:   'ar',   # rabic - Lebanon
               4097:    'ar',   # rabic - Libya
               6145:    'ar',   # rabic - Morocco
               8193:    'ar',   # rabic - Oman
               16385:   'ar',   # rabic - Qatar
               10241:   'ar',   # rabic - Syria
               7169:    'ar',   # rabic - Tunisia
               14337:   'ar',   # rabic - U.A.E.
               9217:    'ar',   # rabic - Yemen
               1067:    'hy',   # rmenian - Armenia
               1101:    'as',   # ssamese
               2092:    'az',   # zeri (Cyrillic)
               1068:    'az',   # zeri (Latin)
               1069:    'eu',   # asque
               1059:    'be',   # elarusian
               1093:    'bn',   # engali (India)
               2117:    'bn',   # engali (Bangladesh)
               5146:    'bs',   # osnian (Bosnia/Herzegovina)
               1026:    'bg',   # ulgarian
               1109:    'my',   # urmese
               1027:    'ca',   # atalan
               1116:    'chr',  # herokee - United States
               2052:    'zh',   # hinese - People's Republic of China
               4100:    'zh',   # hinese - Singapore
               1028:    'zh',   # hinese - Taiwan
               3076:    'zh',   # hinese - Hong Kong SAR
               5124:    'zh',   # hinese - Macao SAR
               1050:    'hr',   # roatian
               4122:    'hr',   # roatian (Bosnia/Herzegovina)
               1029:    'cs',   # zech
               1030:    'da',   # anish
               1125:    'dv',   # ivehi
               1043:    'nl',   # utch - Netherlands
               2067:    'nl',   # utch - Belgium
               1126:    'bin',  # do
               1033:    'en',   # nglish - United States
               2057:    'en',   # nglish - United Kingdom
               3081:    'en',   # nglish - Australia
               10249:   'en',   # nglish - Belize
               4105:    'en',   # nglish - Canada
               9225:    'en',   # nglish - Caribbean
               15369:   'en',   # nglish - Hong Kong SAR
               16393:   'en',   # nglish - India
               14345:   'en',   # nglish - Indonesia
               6153:    'en',   # nglish - Ireland
               8201:    'en',   # nglish - Jamaica
               17417:   'en',   # nglish - Malaysia
               5129:    'en',   # nglish - New Zealand
               13321:   'en',   # nglish - Philippines
               18441:   'en',   # nglish - Singapore
               7177:    'en',   # nglish - South Africa
               11273:   'en',   # nglish - Trinidad
               12297:   'en',   # nglish - Zimbabwe
               1061:    'et',   # stonian
               1080:    'fo',   # aroese
               1065:    None,   # ODO: Farsi
               1124:    'fil',  # ilipino
               1035:    'fi',   # innish
               1036:    'fr',   # rench - France
               2060:    'fr',   # rench - Belgium
               11276:   'fr',   # rench - Cameroon
               3084:    'fr',   # rench - Canada
               9228:    'fr',   # rench - Democratic Rep. of Congo
               12300:   'fr',   # rench - Cote d'Ivoire
               15372:   'fr',   # rench - Haiti
               5132:    'fr',   # rench - Luxembourg
               13324:   'fr',   # rench - Mali
               6156:    'fr',   # rench - Monaco
               14348:   'fr',   # rench - Morocco
               58380:   'fr',   # rench - North Africa
               8204:    'fr',   # rench - Reunion
               10252:   'fr',   # rench - Senegal
               4108:    'fr',   # rench - Switzerland
               7180:    'fr',   # rench - West Indies
               1122:    'fy',   # risian - Netherlands
               1127:    None,   # ODO: Fulfulde - Nigeria
               1071:    'mk',   # YRO Macedonian
               2108:    'ga',   # aelic (Ireland)
               1084:    'gd',   # aelic (Scotland)
               1110:    'gl',   # alician
               1079:    'ka',   # eorgian
               1031:    'de',   # erman - Germany
               3079:    'de',   # erman - Austria
               5127:    'de',   # erman - Liechtenstein
               4103:    'de',   # erman - Luxembourg
               2055:    'de',   # erman - Switzerland
               1032:    'el',   # reek
               1140:    'gn',   # uarani - Paraguay
               1095:    'gu',   # ujarati
               1128:    'ha',   # ausa - Nigeria
               1141:    'haw',  # awaiian - United States
               1037:    'he',   # ebrew
               1081:    'hi',   # indi
               1038:    'hu',   # ungarian
               1129:    None,   # ODO: Ibibio - Nigeria
               1039:    'is',   # celandic
               1136:    'ig',   # gbo - Nigeria
               1057:    'id',   # ndonesian
               1117:    'iu',   # nuktitut
               1040:    'it',   # talian - Italy
               2064:    'it',   # talian - Switzerland
               1041:    'ja',   # apanese
               1099:    'kn',   # annada
               1137:    'kr',   # anuri - Nigeria
               2144:    'ks',   # ashmiri
               1120:    'ks',   # ashmiri (Arabic)
               1087:    'kk',   # azakh
               1107:    'km',   # hmer
               1111:    'kok',  # onkani
               1042:    'ko',   # orean
               1088:    'ky',   # yrgyz (Cyrillic)
               1108:    'lo',   # ao
               1142:    'la',   # atin
               1062:    'lv',   # atvian
               1063:    'lt',   # ithuanian
               1086:    'ms',   # alay - Malaysia
               2110:    'ms',   # alay - Brunei Darussalam
               1100:    'ml',   # alayalam
               1082:    'mt',   # altese
               1112:    'mni',  # anipuri
               1153:    'mi',   # aori - New Zealand
               1102:    'mr',   # arathi
               1104:    'mn',   # ongolian (Cyrillic)
               2128:    'mn',   # ongolian (Mongolian)
               1121:    'ne',   # epali
               2145:    'ne',   # epali - India
               1044:    'no',   # orwegian (Bokmￃﾥl)
               2068:    'no',   # orwegian (Nynorsk)
               1096:    'or',   # riya
               1138:    'om',   # romo
               1145:    'pap',  # apiamentu
               1123:    'ps',   # ashto
               1045:    'pl',   # olish
               1046:    'pt',   # ortuguese - Brazil
               2070:    'pt',   # ortuguese - Portugal
               1094:    'pa',   # unjabi
               2118:    'pa',   # unjabi (Pakistan)
               1131:    'qu',   # uecha - Bolivia
               2155:    'qu',   # uecha - Ecuador
               3179:    'qu',   # uecha - Peru
               1047:    'rm',   # haeto-Romanic
               1048:    'ro',   # omanian
               2072:    'ro',   # omanian - Moldava
               1049:    'ru',   # ussian
               2073:    'ru',   # ussian - Moldava
               1083:    'se',   # ami (Lappish)
               1103:    'sa',   # anskrit
               1132:    'nso',  # epedi
               3098:    'sr',   # erbian (Cyrillic)
               2074:    'sr',   # erbian (Latin)
               1113:    'sd',   # indhi - India
               2137:    'sd',   # indhi - Pakistan
               1115:    'si',   # inhalese - Sri Lanka
               1051:    'sk',   # lovak
               1060:    'sl',   # lovenian
               1143:    'so',   # omali
               1070:    'wen',  # orbian
               3082:    'es',   # panish - Spain (Modern Sort)
               1034:    'es',   # panish - Spain (Traditional Sort)
               11274:   'es',   # panish - Argentina
               16394:   'es',   # panish - Bolivia
               13322:   'es',   # panish - Chile
               9226:    'es',   # panish - Colombia
               5130:    'es',   # panish - Costa Rica
               7178:    'es',   # panish - Dominican Republic
               12298:   'es',   # panish - Ecuador
               17418:   'es',   # panish - El Salvador
               4106:    'es',   # panish - Guatemala
               18442:   'es',   # panish - Honduras
               58378:   'es',   # panish - Latin America
               2058:    'es',   # panish - Mexico
               19466:   'es',   # panish - Nicaragua
               6154:    'es',   # panish - Panama
               15370:   'es',   # panish - Paraguay
               10250:   'es',   # panish - Peru
               20490:   'es',   # panish - Puerto Rico
               21514:   'es',   # panish - United States
               14346:   'es',   # panish - Uruguay
               8202:    'es',   # panish - Venezuela
               1072:    None,   # ODO: Sutu
               1089:    'sw',   # wahili
               1053:    'sv',   # wedish
               2077:    'sv',   # wedish - Finland
               1114:    'syr',  # yriac
               1064:    'tg',   # ajik
               1119:    None,   # ODO: Tamazight (Arabic)
               2143:    None,   # ODO: Tamazight (Latin)
               1097:    'ta',   # amil
               1092:    'tt',   # atar
               1098:    'te',   # elugu
               1054:    'th',   # hai
               2129:    'bo',   # ibetan - Bhutan
               1105:    'bo',   # ibetan - People's Republic of China
               2163:    'ti',   # igrigna - Eritrea
               1139:    'ti',   # igrigna - Ethiopia
               1073:    'ts',   # songa
               1074:    'tn',   # swana
               1055:    'tr',   # urkish
               1090:    'tk',   # urkmen
               1152:    'ug',   # ighur - China
               1058:    'uk',   # krainian
               1056:    'ur',   # rdu
               2080:    'ur',   # rdu - India
               2115:    'uz',   # zbek (Cyrillic)
               1091:    'uz',   # zbek (Latin)
               1075:    've',   # enda
               1066:    'vi',   # ietnamese
               1106:    'cy',   # elsh
               1076:    'xh',   # hosa
               1144:    'ii',   # i
               1085:    'yi',   # iddish
               1130:    'yo',   # oruba
               1077:    'zu'}   # ulu

    return mapping[lcid]


def _getscreenlanguage():
    '''
    :returns: the ISO 639-x language code for this session.

    If the LANGUAGE environment variable is set, it's value overrides
    the screen language detection. Otherwise the screen language is
    determined by the currently selected Microsoft Windows MUI language
    pack or the Microsoft Windows installation language.

    Works on Microsoft Windows 2000 and up.
    '''
    if sys.platform == 'win32' or sys.platform == 'nt':
        # Start with nothing
        lang = None

        # Check the LANGUAGE environment variable
        lang = os.getenv('LANGUAGE')

        if lang is None:
            # Start with nothing
            lcid = None

            try:
                from ctypes import windll
                lcid = windll.kernel32.GetUserDefaultUILanguage()
            except:
                logger.debug('Failed to get current screen language '
                             'with \'GetUserDefaultUILanguage\'')
            finally:
                if lcid is None:
                    lang = 'C'
                else:
                    lang = _isofromlcid(lcid)

                logger.debug('Windows screen language is \'%s\' '
                             '(lcid %s)' % (lang, lcid))

        return lang


def _putenv(name, value):
    '''
    :param name: environment variable name
    :param value: environment variable value

    This function ensures that changes to an environment variable are
    applied to each copy of the environment variables used by a process.
    Starting from Python 2.4, os.environ changes only apply to the copy
    Python keeps (os.environ) and are no longer automatically applied to
    the other copies for the process.

    On Microsoft Windows, each process has multiple copies of the
    environment variables, one managed by the OS and one managed by the
    C library. We also need to take care of the fact that the C library
    used by Python is not necessarily the same as the C library used by
    pygtk and friends. This because the latest releases of pygtk and
    friends are built with mingw32 and are thus linked against
    msvcrt.dll. The official gtk+ binaries have always been built in
    this way.
    '''

    if sys.platform == 'win32' or sys.platform == 'nt':
        from ctypes import windll
        from ctypes import cdll
        from ctypes.util import find_msvcrt

        # Update Python's copy of the environment variables
        os.environ[name] = value

        # Update the copy maintained by Windows (so SysInternals
        # Process Explorer sees it)
        try:
            result = windll.kernel32.SetEnvironmentVariableW(name, value)
            if result == 0:
                raise Warning
        except Exception:
            logger.debug('Failed to set environment variable \'%s\' '
                         '(\'kernel32.SetEnvironmentVariableW\')' % name)
        else:
            logger.debug('Set environment variable \'%s\' to \'%s\' '
                         '(\'kernel32.SetEnvironmentVariableW\')' %
                         (name, value))

        # Update the copy maintained by msvcrt (used by gtk+ runtime)
        try:
            result = cdll.msvcrt._putenv('%s=%s' % (name, value))
            if result != 0:
                raise Warning
        except Exception:
            logger.debug('Failed to set environment variable \'%s\' '
                         '(\'msvcrt._putenv\')' % name)
        else:
            logger.debug('Set environment variable \'%s\' to \'%s\' '
                         '(\'msvcrt._putenv\')' % (name, value))

        # Update the copy maintained by whatever c runtime is used by Python
        try:
            msvcrt = find_msvcrt()
            msvcrtname = str(msvcrt).split('.')[0] \
                if '.' in msvcrt else str(msvcrt)
            result = cdll.LoadLibrary(msvcrt)._putenv('%s=%s' % (name, value))
            if result != 0:
                raise Warning
        except Exception:
            logger.debug('Failed to set environment variable \'%s\' '
                         '(\'%s._putenv\')' % (name, msvcrtname))
        else:
            logger.debug('Set environment variable \'%s\' to \'%s\' '
                         '(\'%s._putenv\')' % (name, value, msvcrtname))


def _dugettext(domain, message):
    '''
    :param domain: translation domain
    :param message: message to translate
    :returns: the translated message

    Unicode version of :func:`gettext.dgettext`.
    '''
    try:
        t = gettext.translation(domain, gettext._localedirs.get(domain, None),
                                codeset=gettext._localecodesets.get(domain))
    except IOError:
        return message
    else:
        return t.ugettext(message)


def _install(domain, localedir, asglobal=False):
    '''
    :param domain: translation domain
    :param localedir: locale directory
    :param asglobal: if True, installs the function _() in Python’s
            builtin namespace. Default is False

    Private function doing all the work for the :func:`elib.intl.install` and
    :func:`elib.intl.install_module` functions.
    '''
    # prep locale system
    if asglobal:
        locale.setlocale(locale.LC_ALL, '')

        # on windows systems, set the LANGUAGE environment variable
        if sys.platform == 'win32' or sys.platform == 'nt':
            _putenv('LANGUAGE', _getscreenlanguage())

    # The locale module on Max OS X lacks bindtextdomain so we specifically
    # test on linux2 here. See commit 4ae8b26fd569382ab66a9e844daa0e01de409ceb
    if sys.platform == 'linux2':
        locale.bindtextdomain(domain, localedir)
        locale.bind_textdomain_codeset(domain, 'UTF-8')
        locale.textdomain(domain)

    # initialize Python's gettext interface
    gettext.bindtextdomain(domain, localedir)
    gettext.bind_textdomain_codeset(domain, 'UTF-8')

    if asglobal:
        gettext.textdomain(domain)

    # on windows systems, initialize libintl
    if sys.platform == 'win32' or sys.platform == 'nt':
        from ctypes import cdll
        libintl = cdll.intl
        libintl.bindtextdomain(domain, localedir)
        libintl.bind_textdomain_codeset(domain, 'UTF-8')

        if asglobal:
            libintl.textdomain(domain)

        del libintl


def install(domain, localedir):
    '''
    :param domain: translation domain
    :param localedir: locale directory

    Installs the function _() in Python’s builtin namespace, based on
    domain and localedir. Codeset is always UTF-8.

    As seen below, you usually mark the strings in your application that are
    candidates for translation, by wrapping them in a call to the _() function,
    like this:

    .. sourcecode:: python

        import elib.intl
        elib.intl.install('myapplication', '/path/to/usr/share/locale')
        print _('This string will be translated.')

    Note that this is only one way, albeit the most convenient way,
    to make the _() function available to your application. Because it affects
    the entire application globally, and specifically Python’s built-in
    namespace, localized modules should never install _(). Instead, you should
    use :func:`elib.intl.install_module` to make _() available to your module.
    '''
    _install(domain, localedir, True)
    gettext.install(domain, localedir, unicode=True)


def install_module(domain, localedir):
    '''
    :param domain: translation domain
    :param localedir: locale directory
    :returns: an anonymous function object, based on domain and localedir.
              Codeset is always UTF-8.

    You may find this function usefull when writing localized modules.
    Use this code to make _() available to your module:

    .. sourcecode:: python

        import elib.intl
        _ = elib.intl.install_module('mymodule', '/path/to/usr/share/locale')
        print _('This string will be translated.')

    When writing packages, you can usually do this in the package's __init__.py
    file and import the _() function from the package namespace as needed.
    '''
    _install(domain, localedir, False)
    return lambda message: _dugettext(domain, message)
