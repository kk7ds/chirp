import datetime
import json
import logging
import math
import os

import requests

from chirp import chirp_common
from chirp import errors
from chirp import platform as chirp_platform
from chirp.sources import base
from chirp.wxui import fips

LOG = logging.getLogger(__name__)

NA_COUNTRIES = [
    'United States',
    'Canada',
    'Mexico',
]
MEXICO_STATES = [
    "Aguascalientes", "Baja California Sur", "Baja California",
    "Campeche", "Chiapas", "Chihuahua", "Coahuila", "Colima",
    "Durango", "Guanajuato", "Guerrero", "Hidalgo", "Jalisco",
    "Mexico City", "Mexico", "Michoacán", "Morelos", "Nayarit",
    "Nuevo Leon", "Puebla", "Queretaro", "Quintana Roo", "San Luis Potosi",
    "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala", "Veracruz",
    "Yucatan", "Zacatecas",
]
STATES = {
    'United States': [s for s, i in fips.FIPS_STATES.items()
                      if isinstance(i, int)],
    'Canada': [s for s, i in fips.FIPS_STATES.items()
               if isinstance(i, str)],
    'Mexico': MEXICO_STATES,
}
MODES = ['FM', 'DV', 'DMR', 'DN']


def parse_tone(val):
    if val.startswith('D'):
        mode = 'DTCS'
        val = int(val[1:])
    elif '.' in val:
        mode = 'Tone'
        val = float(val)
    elif val in ('CSQ', 'Restricted'):
        val = mode = None
    elif val:
        LOG.warning('Unsupported PL format: %r' % val)
        val = mode = None
    else:
        val = mode = None
    return mode, val


def distance(lat_a, lon_a, lat_b, lon_b):
    lat_a = math.radians(lat_a)
    lon_a = math.radians(lon_a)

    lat_b = math.radians(lat_b)
    lon_b = math.radians(lon_b)

    earth_radius_km = 6371

    dlon = lon_b - lon_a
    dlat = lat_b - lat_a

    a = math.sin(dlat / 2)**2 + math.cos(lat_a) * \
        math.cos(lat_b) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return earth_radius_km * c


class RepeaterBook(base.NetworkResultRadio):
    VENDOR = 'RepeaterBook'

    def get_label(self):
        return 'RepeaterBook'

    def get_data(self, status, country, state, service):
        # Ideally we would be able to pull the whole database, but right
        # now this is limited to 3500 results, so we need to filter and
        # cache by state to stay under that limit.
        fn = 'rb%s-%s-%s.json' % (service,
                                  country.lower().replace(' ', '_'),
                                  state.lower().replace(' ', '_'))
        db_dir = chirp_platform.get_platform().config_file('repeaterbook')
        try:
            os.mkdir(db_dir)
        except FileExistsError:
            pass
        except Exception as e:
            LOG.exception('Failed to create %s: %s' % (db_dir, e))
            status.set_fail('Internal error - check log')
            return
        data_file = os.path.join(db_dir, fn)
        try:
            modified = os.path.getmtime(data_file)
        except FileNotFoundError:
            modified = 0
        modified_dt = datetime.datetime.fromtimestamp(modified)
        interval = datetime.timedelta(days=30)
        if datetime.datetime.now() - modified_dt < interval:
            return data_file
        if modified == 0:
            LOG.debug('RepeaterBook database %s not cached' % fn)
        else:
            LOG.debug('RepeaterBook database %s too old: %s',
                      fn, modified_dt)

        params = {'country': country,
                  'stype': service}
        if country in NA_COUNTRIES:
            export = 'export.php'
        else:
            export = 'exportROW.php'
        if country in STATES:
            params['state'] = state

        r = requests.get('https://www.repeaterbook.com/api/%s' % export,
                         headers=base.HEADERS,
                         params=params,
                         stream=True)
        if r.status_code != 200:
            if modified:
                status.send_status('Using cached data', 50)
            status.send_fail('Got error code %i from server' % r.status_code)
            return
        tmp = data_file + '.tmp'
        chunk_size = 8192
        probable_end = 3 << 20
        counter = 0
        data = b''
        with open(tmp, 'wb') as f:
            for chunk in r.iter_content(chunk_size=chunk_size):
                f.write(chunk)
                data += chunk
                counter += len(chunk)
                status.send_status('Downloading', counter / probable_end * 50)
        try:
            results = json.loads(data)
        except Exception as e:
            LOG.exception('Invalid JSON in response: %s' % e)
            status.send_fail('RepeaterBook returned invalid response')
            return

        if results['count']:
            try:
                os.rename(tmp, data_file)
            except FileExistsError:
                # Windows can't do atomic rename
                os.remove(data_file)
                os.rename(tmp, data_file)
        else:
            os.remove(tmp)
            status.send_fail('No results!')
            return

        status.send_status('Download complete', 50)
        return data_file

    def item_to_memory(self, item, number):
        if item.get('D-Star') == 'Yes':
            m = chirp_common.DVMemory()
            m.dv_urcall = 'CQCQCQ'.ljust(8)
            m.dv_rpt1call = item.get('Callsign')[:8].ljust(8)
            m.dv_rpt2call = item.get('Callsign')[:8].ljust(8)
        else:
            m = chirp_common.Memory()
        m.number = number
        m.freq = chirp_common.parse_freq(item['Frequency'])
        try:
            m.tuning_step = chirp_common.required_step(m.freq)
        except errors.InvalidDataError as e:
            LOG.debug(e)
        txf = chirp_common.parse_freq(item['Input Freq'])
        if txf == 0:
            m.duplex = 'off'
        else:
            chirp_common.split_to_offset(m, m.freq, txf)
        txm, tx = parse_tone(item['PL'])
        rxm, rx = parse_tone(item['TSQ'])
        chirp_common.split_tone_decode(m, (txm, tx, 'N'), (rxm, rx, 'N'))
        if item['DMR'] == 'Yes':
            m.mode = 'DMR'
        elif item['D-Star'] == 'Yes':
            m.mode = 'DV'
        elif item['System Fusion'] == 'Yes':
            m.mode = 'DN'
        elif item['FM Analog'] == 'Yes':
            m.mode = 'FM'
        else:
            LOG.warning('Unable to determine mode for repeater %s' % (
                item['Rptr ID']))
            return None
        if 'State' in item and 'County' in item:
            m.comment = (
                '%(Callsign)s near %(Nearest City)s, %(County)s County, '
                '%(State)s %(Use)s') % item
        else:
            m.comment = (
                '%(Callsign)s near %(Nearest City)s, %(Region)s '
                '%(Use)s') % item
        m.comment += ' ' + item.get('Notes', '')
        m.comment = m.comment.strip()
        m.name = item['Landmark'] or item['Callsign']
        return m

    def do_fetch(self, status, params):
        lat = float(params.pop('lat') or 0)
        lon = float(params.pop('lon') or 0)
        dist = int(params.pop('dist') or 0)
        search_filter = params.pop('filter', '')
        bands = params.pop('bands', [])
        modes = params.pop('modes', [])
        fmconv = params.pop('fmconv', False)
        openonly = params.pop('openonly')

        data_file = self.get_data(status,
                                  params.get('country'),
                                  params.pop('state'),
                                  params.get('service', ''))
        if not data_file:
            return

        status.send_status('Parsing', 50)

        def sorter(item):
            if lat == 0 and lon == 0:
                # No sort if not provided
                return 0
            if not item.get('Lat') or not item.get('Long'):
                # Invalid or missing coordinates
                return 0
            return distance(lat, lon,
                            float(item.get('Lat', 0)),
                            float(item.get('Long', 0)))

        def match(item):
            search_fields = ('County', 'State', 'Landmark', 'Nearest City',
                             'Callsign', 'Region', 'Notes')
            content = ' '.join(item.get(k) or '' for k in search_fields
                               if k in item)
            return (not search_filter or
                    search_filter.lower() in content.lower())

        def open_repeater(item):
            return item['Use'] == 'OPEN'

        def included_band(item):
            if not bands:
                return True
            for lo, hi in bands:
                if lo < chirp_common.parse_freq(item['Frequency']) < hi:
                    return True
            return False

        i = 0
        for item in sorted(json.loads(open(data_file, 'rb').read())['results'],
                           key=sorter):
            if not item:
                continue
            if openonly and not open_repeater(item):
                continue
            if item['Operational Status'] != 'On-air':
                continue
            if dist and lat and lon and (
                distance(lat, lon,
                         float(item.get('Lat') or 0),
                         float(item.get('Long') or 0)) > dist):
                continue
            if not match(item):
                continue
            if not included_band(item):
                continue
            i += 1
            try:
                m = self.item_to_memory(item, i)
            except Exception as e:
                LOG.warning('Unable to convert repeater %s: %s',
                            item['Rptr ID'], e)
                continue
            if not m:
                continue
            # Convert any non-FM repeater to FM if user requested it
            if m.mode != 'FM' and fmconv and item.get('FM Analog') == 'Yes':
                LOG.debug('Converting repeater %r from %r to FM: %s',
                          item['Rptr ID'], m.mode, m.comment)
                m.mode = 'FM'
            if modes and m.mode not in modes:
                continue
            self._memories.append(m)

        self.MODEL = '%s %s' % (params.get('country'),
                                params.get('service_display') or 'Result')

        if not self._memories:
            status.send_fail(_('No results!'))
            return

        status.send_end()


ROW_COUNTRIES = [
    "Albania",
    "Andorra",
    "Argentina",
    "Australia",
    "Austria",
    "Azerbaijan",
    "Bahamas",
    "Barbados",
    "Belarus",
    "Belgium",
    "Belize",
    "Bolivia",
    "Bosnia and Herzegovina",
    "Brazil",
    "Bulgaria",
    "Caribbean Netherlands",
    "Cayman Islands",
    "Chile",
    "China",
    "Colombia",
    "Costa Rica",
    "Croatia",
    "Curacao",
    "Cyprus",
    "Czech Republic",
    "Denmark",
    "Dominican Republic",
    "Ecuador",
    "El Salvador",
    "Estonia",
    "Faroe Islands",
    "Finland",
    "France",
    "Georgia",
    "Germany",
    "Greece",
    "Grenada",
    "Guatemala",
    "Guernsey",
    "Haiti",
    "Honduras",
    "Hungary",
    "Iceland",
    "India",
    "Indonesia",
    "Ireland",
    "Isle of Man",
    "Israel",
    "Italy",
    "Jamaica",
    "Japan",
    "Jersey",
    "Kosovo",
    "Kuwait",
    "Latvia",
    "Liechtenstein",
    "Lithuania",
    "Luxembourg",
    "Macedonia",
    "Malaysia",
    "Malta",
    "Moldova",
    "Morocco",
    "Namibia",
    "Nepal",
    "Netherlands",
    "New Zealand",
    "Nicaragua",
    "Norway",
    "Oman",
    "Panama",
    "Paraguay",
    "Peru",
    "Philippines",
    "Poland",
    "Portugal",
    "Romania",
    "Russian Federation",
    "Saint Kitts and Nevis",
    "Saint Vincent and the Grenadines",
    "San Marino",
    "Serbia",
    "Singapore",
    "Slovakia",
    "Slovenia",
    "South Africa",
    "South Korea",
    "Spain",
    "Sri Lanka",
    "Sweden",
    "Switzerland",
    "Taiwan",
    "Thailand",
    "Trinidad and Tobago",
    "Turkey",
    "Ukraine",
    "United Arab Emirates",
    "United Kingdom",
    "Uruguay",
    "Venezuela",
]

COUNTRIES = list(sorted(NA_COUNTRIES + ROW_COUNTRIES))
