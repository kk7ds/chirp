"""AMSAT and SatNOGS data sources"""

import logging
import re
import requests

from chirp import chirp_common
from chirp import errors
from chirp.sources import base

LOG = logging.getLogger(__name__)

DATA_URL = ('https://raw.githubusercontent.com/palewire/'
            'amateur-satellite-database/main/data/'
            'amsat-active-frequencies.json')
SATNOGS_SATS_URL = 'https://db.satnogs.org/api/satellites/?status=alive'
SATNOGS_TRANS_URL = ('https://db.satnogs.org/api/transmitters/'
                     '?alive=True&status=active')


class RadioAmateurSatellites(base.NetworkResultRadio):
    """Radio Amateur Satellite database (AMSAT active frequencies)"""
    VENDOR = 'Radio Amateur'
    MODEL = 'Satellites'

    def get_label(self):
        return 'Radio Amateur Satellites'

    def item_to_memory(self, item):
        """Convert a JSON item to a Memory object"""
        mem = chirp_common.Memory()

        # Satellite name and NORAD ID
        name = item.get('name', 'Unknown')
        norad_id = item.get('norad_id', 'Unknown')
        mem.name = name[:16]  # Most radios have limited name length

        # Frequencies
        # The JSON can have Multiple frequencies separated by / or -
        # We'll take the first one for now, or handle ranges if possible.
        # Downlink is the primary frequency for listening.
        downlink_str = item.get('downlink')
        if not downlink_str:
            LOG.debug('No downlink for %s, skipping', name)
            return None

        # Simplistic parsing of the first frequency in the string
        try:
            # Handle cases like "436.270/10473.350" or "145.850-145.950"
            first_freq = downlink_str.replace('/', ' ').replace('-', ' ')
            first_freq = first_freq.split()[0]
            # Remove asterisks or other markers
            first_freq = ''.join(c for c in first_freq
                                 if c.isdigit() or c == '.')
            mem.freq = chirp_common.parse_freq(first_freq)
        except (ValueError, IndexError, errors.InvalidDataError) as e:
            LOG.warning('Unable to parse downlink freq %r for %s: %s',
                        downlink_str, name, e)
            return None

        # Uplink for Duplex
        uplink_str = item.get('uplink')
        if uplink_str:
            try:
                first_uplink = uplink_str.replace('/', ' ').replace('-', ' ')
                first_uplink = first_uplink.split()[0]
                first_uplink = ''.join(c for c in first_uplink
                                       if c.isdigit() or c == '.')
                tx_freq = chirp_common.parse_freq(first_uplink)
                if tx_freq > 0:
                    chirp_common.split_to_offset(mem, mem.freq, tx_freq)
            except (ValueError, IndexError, errors.InvalidDataError) as e:
                LOG.debug('Unable to parse uplink freq %r for %s: %s',
                          uplink_str, name, e)

        # Mode parsing
        mode_str = (item.get('mode') or '').upper()
        if 'FM' in mode_str:
            mem.mode = 'FM'
        elif 'SSB' in mode_str or 'LINEAR' in mode_str:
            mem.mode = 'USB'  # Satellites typically use USB
        elif 'CW' in mode_str:
            mem.mode = 'CW'
        else:
            mem.mode = 'FM'  # Default to FM for wide compatibility

        # Tone parsing (basic)
        if 'CTCSS' in mode_str:
            # Try to find something like "67.0Hz"
            match = re.search(r'(\d+\.?\d*)\s*HZ', mode_str)
            if match:
                mem.rtone = float(match.group(1))
                mem.tmode = 'Tone'

        # Comment field with relevant info
        # Remove NORAD:<id> as it is not useful info for most users
        mem.comment = 'Mode:%s' % item.get('mode', 'Unknown')
        if item.get('satnogs_id'):
            mem.comment += ' Info: https://db.satnogs.org/satellite/%s' % \
                norad_id

        mem.comment = mem.comment.strip()
        return mem

    def do_fetch(self, status, params):
        status.send_status('Downloading satellite data...', 10)

        try:
            resp = requests.get(DATA_URL, headers=base.HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            LOG.exception('Failed to download satellite data: %s', e)
            status.send_fail('Failed to download data: %s' % e)
            return

        status.send_status('Parsing data...', 50)

        i = 0
        for item in data:
            try:
                mem = self.item_to_memory(item)
                if mem:
                    mem.number = i
                    self._memories.append(mem)
                    i += 1
            except Exception as e:
                LOG.warning('Failed to convert satellite %s: %s',
                            item.get('name'), e)
                continue

        if not self._memories:
            status.send_fail('No valid satellite frequencies found!')
            return

        status.send_status('Done', 100)
        status.send_end()


class SatNOGS(base.NetworkResultRadio):
    """SatNOGS database source"""
    VENDOR = 'SatNOGS'
    MODEL = 'DB'

    def get_label(self):
        return 'SatNOGS DB'

    def item_to_memory(self, item):
        """Convert a SatNOGS transmitter item to a Memory object"""
        mem = chirp_common.Memory()

        # Satellite info is pre-merged into the item in do_fetch
        sat = item.get('_satellite', {})
        sat_name = sat.get('name', 'Unknown')
        trans_desc = item.get('description', '')

        if trans_desc:
            mem.name = ('%s %s' % (sat_name, trans_desc))[:16].strip()
        else:
            mem.name = sat_name[:16]

        # Frequency (downlink_low is in Hz)
        freq_hz = item.get('downlink_low')
        if not freq_hz:
            return None
        mem.freq = int(freq_hz)

        # Uplink/Duplex
        uplink_hz = item.get('uplink_low')
        if uplink_hz:
            tx_freq = int(uplink_hz)
            if tx_freq > 0:
                chirp_common.split_to_offset(mem, mem.freq, tx_freq)

        # Mode mapping
        orig_mode = (item.get('mode') or '').upper()
        mem.mode = 'FM'  # Default
        if orig_mode == 'FMN':
            mem.mode = 'NFM'
        elif orig_mode == 'DSB':
            mem.mode = 'AM'  # DSB is a form of AM
        elif orig_mode in chirp_common.MODES:
            mem.mode = orig_mode
        elif 'FM' in orig_mode:
            mem.mode = 'FM'
        elif 'USB' in orig_mode or 'LINEAR' in orig_mode:
            mem.mode = 'USB'
        elif 'LSB' in orig_mode:
            mem.mode = 'LSB'
        elif 'CW' in orig_mode:
            mem.mode = 'CW'
        elif any(m in orig_mode for m in ['PSK', 'FSK', 'MSK', 'GMSK', 'GFSK', 'LORA',
                                          'AFSK', 'APT', 'SSTV', 'DVB', 'AHRPT']):
            mem.mode = 'DIG'

        # Comment
        norad_id = sat.get('norad_cat_id', 'Unknown')
        # Only include mode if it's not natively handled or if it's specialized
        if mem.mode in ['DIG', 'AM'] and orig_mode != mem.mode:
            mem.comment = 'Mode:%s Type:%s' % (
                item.get('mode', 'Unknown'), item.get('type', 'Unknown'))
        else:
            mem.comment = 'Type:%s' % item.get('type', 'Unknown')

        mem.comment += ' Info: https://db.satnogs.org/satellite/%s' % norad_id

        return mem

    def _fetch_all(self, status, url, label):
        """Fetch all pages of results from a paginated API"""
        results = []
        next_url = url
        page = 1

        while next_url:
            status.send_status('Fetching %s (page %i)...' % (label, page),
                               len(results) % 100)
            try:
                resp = requests.get(next_url, headers=base.HEADERS, timeout=30)
                resp.raise_for_status()
                data = resp.json()

                # SatNOGS API uses DRF pagination
                if isinstance(data, dict) and 'results' in data:
                    results.extend(data['results'])
                    next_url = data.get('next')
                else:
                    results.extend(data)
                    next_url = None
                page += 1
            except Exception as e:
                LOG.exception('Failed to fetch %s: %s', label, e)
                break
        return results

    def do_fetch(self, status, params):
        filter_modes = params.get('modes', [])

        status.send_status('Downloading SatNOGS satellites...', 5)
        satellites = self._fetch_all(status, SATNOGS_SATS_URL, 'satellites')

        status.send_status('Downloading SatNOGS transmitters...', 50)
        transmitters = self._fetch_all(status, SATNOGS_TRANS_URL,
                                       'transmitters')

        status.send_status('Processing data...', 90)

        # Index satellites by sat_id
        sat_map = {s['sat_id']: s for s in satellites}

        i = 0
        for trans in transmitters:
            sat_id = trans.get('sat_id')
            if sat_id not in sat_map:
                continue

            trans['_satellite'] = sat_map[sat_id]

            # Filter by mode if requested
            if filter_modes:
                mode = (trans.get('mode') or '').upper()
                if not any(fm in mode for fm in filter_modes):
                    continue

            try:
                mem = self.item_to_memory(trans)
                if mem:
                    mem.number = i
                    self._memories.append(mem)
                    i += 1
            except Exception:
                LOG.exception('Failed to convert SatNOGS entry')
                continue

        if not self._memories:
            status.send_fail('No valid SatNOGS frequencies found!')
            return

        status.send_status('Done', 100)
        status.send_end()
