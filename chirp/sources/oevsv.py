# CHIRP Source Plugin for OEVSV (Österreichischer Versuchssenderverband)
# Austrian Amateur Radio Repeater Database
#
# API Documentation: https://repeater.oevsv.at/api/
#

import logging
import json
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from chirp import chirp_common
from chirp.sources import base

LOG = logging.getLogger(__name__)

# API Base URL
OEVSV_API_BASE = "https://repeater.oevsv.at/api/trx"

# Valid bands available in the OEVSV database
BANDS = [
    ("10m (28 MHz)", "10m"),
    ("6m (50 MHz)", "6m"),
    ("2m (144 MHz)", "2m"),
    ("70cm (430 MHz)", "70cm"),
    ("23cm (1296 MHz)", "23cm"),
]

# Station types available
STATION_TYPES = [
    ("Voice Repeaters", "repeater_voice"),
    ("Digital Repeaters", "repeater_digi"),
    ("Beacons", "beacon"),
    ("APRS Digipeaters", "digipeater"),
]

# Valid CTCSS tones for normalization
VALID_CTCSS_TONES = [
    67.0, 69.3, 71.9, 74.4, 77.0, 79.7, 82.5, 85.4, 88.5, 91.5,
    94.8, 97.4, 100.0, 103.5, 107.2, 110.9, 114.8, 118.8, 123.0, 127.3,
    131.8, 136.5, 141.3, 146.2, 151.4, 156.7, 159.8, 162.2, 165.5, 167.9,
    171.3, 173.8, 177.3, 179.9, 183.5, 186.2, 189.9, 192.8, 196.6, 199.5,
    203.5, 206.5, 210.7, 218.1, 225.7, 229.1, 233.6, 241.8, 250.3, 254.1
]


def normalize_ctcss(tone):
    """Normalize a CTCSS tone to the nearest valid value."""
    if tone is None:
        return None
    try:
        tone = float(tone)
        return min(VALID_CTCSS_TONES, key=lambda x: abs(x - tone))
    except (ValueError, TypeError):
        return None


class OESVVData(base.NetworkResultRadio):
    VENDOR = "oevsv.at"
    MODEL = "Austria"

    def do_fetch(self, status, params):
        status.send_status('Querying repeater.oevsv.at', 0)
        memories = fetch_repeaters(
            bands=params['bands'],
            station_type=params['station_type'],
            fm_only=params['fm_only'],
            active_only=params['active_only'],
            status_cb=lambda msg: status.send_status(msg, 50))
        self._memories = memories
        status.send_status('Complete', 100)
        status.send_end()


def fetch_repeaters(bands, station_type, fm_only, active_only, status_cb=None):
    """
    Fetch repeaters from the OEVSV API.

    Args:
        bands: List of band strings (e.g., ['2m', '70cm'])
        station_type: Station type filter (e.g., 'repeater_voice')
        fm_only: Boolean to filter FM-only repeaters
        active_only: Boolean to filter active repeaters only
        status_cb: Optional callback function for status updates

    Returns:
        List of chirp_common.Memory objects
    """
    if isinstance(bands, str):
        bands = [bands]

    all_repeaters = []

    for band in bands:
        if status_cb:
            status_cb(f"Fetching {band} repeaters...")

        try:
            repeaters = _fetch_band(band, station_type, fm_only, active_only)
            for rpt in repeaters:
                rpt['_band'] = band
            all_repeaters.extend(repeaters)
            LOG.info(f"Retrieved {len(repeaters)} repeaters for {band}")
        except Exception as e:
            LOG.error(f"Error fetching {band}: {e}")
            if status_cb:
                status_cb(f"Warning: Could not fetch {band}")

    if not all_repeaters:
        return []

    # Sort by frequency
    all_repeaters.sort(key=lambda x: x.get('frequency_tx', 0))

    # Convert to memories
    memories = []
    for idx, rpt in enumerate(all_repeaters):
        mem = _repeater_to_memory(rpt, idx)
        if mem:
            memories.append(mem)

    return memories


def _fetch_band(band, station_type, fm_only, active_only):
    """Fetch repeaters for a specific band from the API."""
    params = [f"band=eq.{band}"]

    if station_type:
        params.append(f"type_of_station=eq.{station_type}")

    if fm_only:
        params.append("fm=eq.true")

    if active_only:
        params.append("status=eq.active")

    url = f"{OEVSV_API_BASE}?{'&'.join(params)}"
    LOG.debug(f"Fetching from: {url}")

    try:
        request = Request(url)
        request.add_header("User-Agent", "CHIRP-OEVSV-Plugin/1.0")
        request.add_header("Accept", "application/json")

        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode('utf-8'))

    except HTTPError as e:
        LOG.error(f"HTTP error: {e.code} - {e.reason}")
        raise Exception(f"Server error: {e.code}")
    except URLError as e:
        LOG.error(f"URL error: {e.reason}")
        raise Exception(f"Connection error: {e.reason}")
    except json.JSONDecodeError as e:
        LOG.error(f"JSON decode error: {e}")
        raise Exception("Invalid response from server")


def _repeater_to_memory(rpt, number):
    """
    Convert an OEVSV repeater record to a CHIRP Memory object.

    Args:
        rpt: Dictionary containing repeater data from API
        number: Memory channel number

    Returns:
        chirp_common.Memory object or None if conversion fails
    """
    try:
        tx_freq = rpt.get("frequency_tx")
        rx_freq = rpt.get("frequency_rx")

        if not tx_freq or not rx_freq:
            LOG.warning("Skipping repeater with missing frequency: "
                        "%s", rpt.get('callsign'))
            return None

        mem = chirp_common.Memory()
        mem.number = number

        # Frequency - we listen on repeater's TX frequency
        mem.freq = int(tx_freq * 1000000)

        # Name - callsign with optional site info
        callsign = rpt.get("callsign", "")
        site = rpt.get("site_name", "")
        if callsign:
            name = callsign
            if site and len(f"{callsign} {site[:5]}") <= 16:
                name = f"{callsign} {site[:5]}"
            mem.name = name[:16]
        else:
            mem.name = site[:16] if site else "UNKNOWN"

        # Duplex and offset
        # We transmit on repeater's RX, receive on repeater's TX
        offset_hz = int((rx_freq - tx_freq) * 1000000)
        if abs(offset_hz) < 1000:  # Less than 1 kHz = simplex
            mem.duplex = ""
            mem.offset = 0
        elif offset_hz > 0:
            mem.duplex = "+"
            mem.offset = abs(offset_hz)
        else:
            mem.duplex = "-"
            mem.offset = abs(offset_hz)

        # Mode
        mem.mode = "FM"

        # CTCSS tones
        # ctcss_tx = what the repeater transmits (we receive)
        # ctcss_rx = what the repeater expects from us (we transmit)
        ctcss_tx = rpt.get("ctcss_tx")
        ctcss_rx = rpt.get("ctcss_rx")

        if ctcss_tx and ctcss_rx:
            if ctcss_tx == ctcss_rx:
                mem.tmode = "TSQL"
                mem.ctone = normalize_ctcss(ctcss_tx)
                mem.rtone = normalize_ctcss(ctcss_tx)
            else:
                mem.tmode = "Cross"
                mem.cross_mode = "Tone->Tone"
                mem.ctone = normalize_ctcss(ctcss_rx)  # We transmit
                mem.rtone = normalize_ctcss(ctcss_tx)  # We receive
        elif ctcss_rx:
            # Repeater expects tone from us
            mem.tmode = "Tone"
            mem.rtone = normalize_ctcss(ctcss_rx)
        elif ctcss_tx:
            # Repeater sends tone (use TSQL)
            mem.tmode = "TSQL"
            mem.ctone = normalize_ctcss(ctcss_tx)
            mem.rtone = normalize_ctcss(ctcss_tx)
        else:
            mem.tmode = ""

        # Tuning step based on band
        band = rpt.get("_band", rpt.get("band", "70cm"))
        if band in ("2m", "70cm"):
            mem.tuning_step = 12.5
        elif band == "23cm":
            mem.tuning_step = 25.0
        else:
            mem.tuning_step = 5.0

        # Comment with additional info
        comment_parts = []
        comment_parts.append(f"[{band}]")
        if site:
            comment_parts.append(site)
        if rpt.get("sysop"):
            comment_parts.append(f"Sysop:{rpt['sysop']}")
        if rpt.get("echolink") and rpt.get("echolink_id"):
            comment_parts.append(f"EL:{rpt['echolink_id']}")
        if rpt.get("fm_wakeup"):
            comment_parts.append(f"Wakeup:{rpt['fm_wakeup']}")

        # Digital mode indicators
        modes = []
        if rpt.get("dmr"):
            modes.append("DMR")
        if rpt.get("c4fm"):
            modes.append("C4FM")
        if rpt.get("dstar"):
            modes.append("D-STAR")
        if modes:
            comment_parts.append("/".join(modes))

        mem.comment = " | ".join(comment_parts)[:255]

        return mem

    except Exception as e:
        LOG.error(f"Error converting repeater {rpt.get('callsign')}: {e}")
        return None
