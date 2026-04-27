#!/usr/bin/env python

import asyncio
import logging
import math
import sys
import time

from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.exceptions import ModbusException
from pymodbus.server import StartAsyncSerialServer

from shellyPoller import ShellyPoller, ShellySnapshotStore


# --------------------------------------------------
# Konfiguration
# --------------------------------------------------
SERIAL_PORT = "/dev/ttyUSB0"
SHELLY_URL = "http://192.168.178.40/status"
SHELLY_USERNAME = "admin"
SHELLY_PASSWORD = "EEGUmlage"

SHELLY_POLL_INTERVALL = 0.1
SHELLY_POLLTIMEOUT = 2

REGISTER_COUNT = 9000

# Logging-Schalter
ENABLE_LOGGING = False

# Nach dieser Zeit ohne erfolgreiche Shelly-Daten
# werden keine normalen Modbus-Werte mehr geliefert.
STALE_DATA_TIMEOUT_SECONDS = 5.0

# KSEM PnP / Basiserkennung
REG_MEASURING_INTERVAL = 8244
REG_UNIXTIME_START = 8245   # 8245..8248 = uint64 ms #Unixzeit beginnt ab Register 8245
REG_MODBUS_SPEC = 8249

MEASURING_INTERVAL_MS = 500 # Dieses Intervall liefern wir aus als internes Messintervall
MODBUS_SPEC_VERSION = 7 #aus der Dokumentation so übernommen

GRID_FREQUENCY_HZ = 50.0

# KSEM-Einstellungen, brauchen nicht angepasst zu werden
SLAVE_ID = 1
BAUDRATE = 38400
BYTESIZE = 8
PARITY = "N"
STOPBITS = 2


# --------------------------------------------------
# Logging / Statusanzeige
# --------------------------------------------------
STATUS_SPINNER = ["|", "/", "-", "\\"]
_status_mode = None
_status_spinner_index = 0
_status_last_print = 0.0


def log(text: str) -> None:
    if ENABLE_LOGGING:
        print(text)


def show_status_line(text: str, force: bool = False) -> None:
    global _status_last_print
    now = time.perf_counter()

    if not force and now - _status_last_print < 0.5:
        return

    _status_last_print = now
    sys.stdout.write("\r" + text.ljust(90))
    sys.stdout.flush()


def set_stale_status(age_seconds: float | None) -> None:
    global _status_mode, _status_spinner_index
    _status_mode = "stale"

    spinner = STATUS_SPINNER[_status_spinner_index]
    _status_spinner_index = (_status_spinner_index + 1) % len(STATUS_SPINNER)

    if age_seconds is None:
        text = f"KSEM läuft | Shelly: noch keine Daten {spinner}"
    else:
        text = f"KSEM läuft | Shelly: keine frischen Daten seit {age_seconds:.1f}s {spinner}"

    show_status_line(text)


def set_ok_status() -> None:
    global _status_mode
    if _status_mode != "ok":
        _status_mode = "ok"
        show_status_line("KSEM läuft | Shelly: OK", force=True)


# --------------------------------------------------
# Hilfsfunktionen
# --------------------------------------------------
def split_u32(value: int) -> list[int]:
    value &= 0xFFFFFFFF
    return [(value >> 16) & 0xFFFF, value & 0xFFFF]


def split_u64(value: int) -> list[int]:
    value &= 0xFFFFFFFFFFFFFFFF
    return [
        (value >> 48) & 0xFFFF,
        (value >> 32) & 0xFFFF,
        (value >> 16) & 0xFFFF,
        value & 0xFFFF,
    ]


def current_unix_ms() -> int:
    return int(time.time() * 1000)


def apparent_power(volt: float, amp: float) -> float:
    return volt * amp


def reactive_power(power_w: float, voltage_v: float, current_a: float) -> float:
    s = apparent_power(voltage_v, current_a)
    return math.sqrt(max(s * s - power_w * power_w, 0.0))


def safe_pf(power_w: float, apparent_va: float) -> float:
    if apparent_va <= 0:
        return 0.0
    return abs(power_w) / apparent_va


def raw_power(value_w_or_var_or_va: float) -> int:
    return int(round(value_w_or_var_or_va * 10.0))


def raw_current(value_a: float) -> int:
    return int(round(value_a * 1000.0))


def raw_voltage(value_v: float) -> int:
    return int(round(value_v * 1000.0))


def raw_pf(value_pf: float) -> int:
    return int(round(value_pf * 1000.0))


def raw_frequency(value_hz: float) -> int:
    return int(round(value_hz * 1000.0))


def split_by_active_direction(active_power_w: float, magnitude: float) -> tuple[float, float]:
    """
    Ordnet einen Betrag derselben Richtung zu wie die Wirkleistung:

    - active_power_w >= 0  -> Bezug / '+'-Register
    - active_power_w < 0   -> Einspeisung / '-'-Register

    Das benutzen wir für Blind- und Scheinleistung, weil der Shelly dort
    keinen eigenen Richtungswert liefert. So bleiben Q und S konsistent
    zur Richtung von P.
    """
    if active_power_w < 0:
        return 0.0, magnitude
    return magnitude, 0.0


# --------------------------------------------------
# Gemeinsamer Zustand
# --------------------------------------------------
class SharedState:
    def __init__(self, store: ShellySnapshotStore) -> None:
        self.store = store

        # Hier liegt der zuletzt vollständig berechnete Registersatz
        # für die Momentanwerte. Modbus liest nur noch daraus.
        self.cached_runtime_values = [0] * REGISTER_COUNT

        # Signatur des zuletzt verarbeiteten Shelly-Snapshots.
        # Wenn sie gleich bleibt, sparen wir uns die Neuberechnung.
        self._last_signature = None

    def _snapshot_signature(self, data: dict) -> tuple | None:
        emeters = data.get("emeters", [])
        if len(emeters) < 3:
            return None

        # Für eine saubere Neuberechnung betrachten wir die Werte,
        # aus denen die abgeleiteten Größen entstehen:
        #
        # - power
        # - voltage
        # - current
        # - pf
        #
        # Sobald sich einer dieser Werte ändert, berechnen wir den
        # vollständigen Registersatz neu.
        signature = []
        for e in emeters[:3]:
            signature.extend(
                [
                    float(e.get("power", 0.0)),
                    float(e.get("voltage", 0.0)),
                    float(e.get("current", 0.0)),
                    float(e.get("pf", 0.0)),
                ]
            )

        return tuple(signature)

    def update_from_snapshot(self, data: dict) -> None:
        signature = self._snapshot_signature(data)
        if signature is None:
            return

        if signature == self._last_signature:
            return

        values = build_runtime_registers_from_snapshot(data)
        self.cached_runtime_values = values
        self._last_signature = signature



# --------------------------------------------------
# Registersatz aus Shelly-Snapshot berechnen
#
# Wichtig:
# Hier entsteht jetzt ein vollständiger, zusammenhängender Satz
# von Momentanwerten. Dieser Satz wird danach als Ganzes in den
# SharedState übernommen.
#
# Dadurch liest Modbus nicht mehr aus einer laufenden Berechnung,
# sondern immer aus einem konsistenten Snapshot.
# --------------------------------------------------
def build_runtime_registers_from_snapshot(data: dict) -> list[int]:
    values = [0] * REGISTER_COUNT

    def set_u32_doc(doc_reg: int, value: int) -> None:
        hi, lo = split_u32(value)
        values[doc_reg + 1] = hi
        values[doc_reg + 2] = lo

    emeters = data.get("emeters", [])
    if len(emeters) < 3:
        return values

    e1, e2, e3 = emeters[0], emeters[1], emeters[2]

    p1 = float(e1.get("power", 0.0))
    p2 = float(e2.get("power", 0.0))
    p3 = float(e3.get("power", 0.0))

    u1 = float(e1.get("voltage", 0.0))
    u2 = float(e2.get("voltage", 0.0))
    u3 = float(e3.get("voltage", 0.0))

    i1 = float(e1.get("current", 0.0))
    i2 = float(e2.get("current", 0.0))
    i3 = float(e3.get("current", 0.0))

    s1 = apparent_power(u1, i1)
    s2 = apparent_power(u2, i2)
    s3 = apparent_power(u3, i3)

    q1 = reactive_power(abs(p1), u1, i1)
    q2 = reactive_power(abs(p2), u2, i2)
    q3 = reactive_power(abs(p3), u3, i3)

    pf1 = float(e1.get("pf", 0.0)) or safe_pf(p1, s1)
    pf2 = float(e2.get("pf", 0.0)) or safe_pf(p2, s2)
    pf3 = float(e3.get("pf", 0.0)) or safe_pf(p3, s3)

    p_total = p1 + p2 + p3
    s_total = s1 + s2 + s3
    q_total = q1 + q2 + q3
    pf_total = safe_pf(p_total, s_total)

    # Wirkleistung hat echte Richtung:
    # Bezug  -> '+'-Register
    # Einspeisung -> '-'-Register
    p1_plus = max(p1, 0.0)
    p1_minus = max(-p1, 0.0)
    p2_plus = max(p2, 0.0)
    p2_minus = max(-p2, 0.0)
    p3_plus = max(p3, 0.0)
    p3_minus = max(-p3, 0.0)

    p_total_plus = max(p_total, 0.0)
    p_total_minus = max(-p_total, 0.0)

    # Für Blind- und Scheinleistung liefert der Shelly keinen eigenen
    # Richtungswert. Deshalb legen wir Q und S in dieselbe Richtung
    # wie die jeweilige Wirkleistung.
    q_total_plus, q_total_minus = split_by_active_direction(p_total, q_total)
    s_total_plus, s_total_minus = split_by_active_direction(p_total, s_total)

    q1_plus, q1_minus = split_by_active_direction(p1, q1)
    q2_plus, q2_minus = split_by_active_direction(p2, q2)
    q3_plus, q3_minus = split_by_active_direction(p3, q3)

    s1_plus, s1_minus = split_by_active_direction(p1, s1)
    s2_plus, s2_minus = split_by_active_direction(p2, s2)
    s3_plus, s3_minus = split_by_active_direction(p3, s3)

    freq = GRID_FREQUENCY_HZ

    # ----------------------------
    # Gesamt
    # ----------------------------
    set_u32_doc(0, raw_power(p_total_plus))       # Active power+
    set_u32_doc(2, raw_power(p_total_minus))      # Active power-
    set_u32_doc(4, raw_power(q_total_plus))       # Reactive power+
    set_u32_doc(6, raw_power(q_total_minus))      # Reactive power-
    set_u32_doc(16, raw_power(s_total_plus))      # Apparent power+
    set_u32_doc(18, raw_power(s_total_minus))     # Apparent power-
    set_u32_doc(24, raw_pf(pf_total))             # Power factor
    set_u32_doc(26, raw_frequency(freq))          # Supply frequency

    # ----------------------------
    # L1
    # ----------------------------
    set_u32_doc(40, raw_power(p1_plus))
    set_u32_doc(42, raw_power(p1_minus))
    set_u32_doc(44, raw_power(q1_plus))
    set_u32_doc(46, raw_power(q1_minus))
    set_u32_doc(56, raw_power(s1_plus))
    set_u32_doc(58, raw_power(s1_minus))
    set_u32_doc(60, raw_current(i1))
    set_u32_doc(62, raw_voltage(u1))
    set_u32_doc(64, raw_pf(pf1))

    # ----------------------------
    # L2
    # ----------------------------
    set_u32_doc(80, raw_power(p2_plus))
    set_u32_doc(82, raw_power(p2_minus))
    set_u32_doc(84, raw_power(q2_plus))
    set_u32_doc(86, raw_power(q2_minus))
    set_u32_doc(96, raw_power(s2_plus))
    set_u32_doc(98, raw_power(s2_minus))
    set_u32_doc(100, raw_current(i2))
    set_u32_doc(102, raw_voltage(u2))
    set_u32_doc(104, raw_pf(pf2))

    # ----------------------------
    # L3
    # ----------------------------
    set_u32_doc(120, raw_power(p3_plus))
    set_u32_doc(122, raw_power(p3_minus))
    set_u32_doc(124, raw_power(q3_plus))
    set_u32_doc(126, raw_power(q3_minus))
    set_u32_doc(136, raw_power(s3_plus))
    set_u32_doc(138, raw_power(s3_minus))
    set_u32_doc(140, raw_current(i3))
    set_u32_doc(142, raw_voltage(u3))
    set_u32_doc(144, raw_pf(pf3))

    return values


# --------------------------------------------------
# KSEM Datenblock
#
# In diesem Setup gilt:
# Dokumentierte Registeradresse N liegt intern auf self.values[N + 1]
# Das wurde so getestet.
# --------------------------------------------------
class KsemBlock(ModbusSequentialDataBlock):
    def __init__(self, address: int, values: list[int], shared_state: SharedState):
        super().__init__(address, values)
        self.shared_state = shared_state

    def _set_u16_doc(self, doc_reg: int, value: int) -> None:
        self.values[doc_reg + 1] = value & 0xFFFF

    def _set_u64_doc(self, doc_reg: int, value: int) -> None:
        r0, r1, r2, r3 = split_u64(value)
        self.values[doc_reg + 1] = r0
        self.values[doc_reg + 2] = r1
        self.values[doc_reg + 3] = r2
        self.values[doc_reg + 4] = r3

    def _fill_defaults(self) -> None:
        self._set_u16_doc(REG_MEASURING_INTERVAL, MEASURING_INTERVAL_MS)
        self._set_u64_doc(REG_UNIXTIME_START, current_unix_ms())
        self._set_u16_doc(REG_MODBUS_SPEC, MODBUS_SPEC_VERSION)

    def getValues(self, address, count=1):
        # Standardregister immer aktuell halten
        self._fill_defaults()

        # Nur frische Shelly-Daten in die Momentanwerte übernehmen.
        #
        # Es wird ein bereits komplett vorbereiteter
        # Registersatz aus dem SharedState übernommen.
        if self.shared_state.store.has_fresh_data(STALE_DATA_TIMEOUT_SECONDS):
            runtime_values = self.shared_state.cached_runtime_values
            self.values[:] = runtime_values[:]

            # Standardregister danach noch einmal setzen, damit diese
            # wirklich immer aktuell bleiben und nicht vom Cache
            # überschrieben werden.
            self._fill_defaults()

        return super().getValues(address, count)


# --------------------------------------------------
# DeviceContext mit Sperre, wenn Daten nicht aktuell
#
# Wichtig:
# validate() allein reicht hier offenbar nicht zuverlässig.
# Deshalb sitzt die harte Sperre zusätzlich direkt in getValues().
#
# Sobald Shelly-Daten veraltet sind, werfen wir wieder eine
# ModbusException. Das verhindert normale Datenantworten.
#
# Die früher störenden PyModbus-Tracebacks unterdrücken wir
# unten über die Logger-Konfiguration.
# --------------------------------------------------
class GuardedDeviceContext(ModbusDeviceContext):
    def __init__(self, block: KsemBlock, shared_state: SharedState):
        super().__init__(di=block, co=block, hr=block, ir=block)
        self.shared_state = shared_state

    def _has_fresh_data(self) -> bool:
        age = self.shared_state.store.age_seconds()
        if age is None:
            set_stale_status(None)
            return False

        if age > STALE_DATA_TIMEOUT_SECONDS:
            set_stale_status(age)
            return False

        set_ok_status()
        return True

    def validate(self, func_code, address, count=1):
        # Zusätzliche Vorprüfung. Wenn PyModbus diesen Pfad nutzt,
        # wird der Zugriff schon hier abgelehnt.
        if not self._has_fresh_data():
            return False

        return super().validate(func_code, address, count)

    def getValues(self, func_code, address, count=1):
        # Harte Sperre:
        # Sobald keine frischen Shelly-Daten mehr vorliegen,
        # darf PyModbus keine normalen Registerwerte mehr senden.
        #
        # Die PyModbus-Fehlerlogs werden unten stummgeschaltet.
        if not self._has_fresh_data():
            raise ModbusException("Shelly data stale")

        return super().getValues(func_code, address, count)

# --------------------------------------------------
# Logging der Telegramme
# --------------------------------------------------
def trace_packet(_is_request, packet):
    if not ENABLE_LOGGING:
        return packet

    if len(packet) < 2:
        return packet

    slave = packet[0]
    fc = packet[1]

    # Requests FC03 / FC04
    if fc in (3, 4) and len(packet) == 8:
        addr = (packet[2] << 8) | packet[3]
        count = (packet[4] << 8) | packet[5]
        log(f"request slave={slave} fc={fc} addr={addr} count={count}")

    # Responses FC03 / FC04
    elif fc in (3, 4) and len(packet) >= 5:
        bytecount = packet[2]
        if len(packet) == bytecount + 5:
            data_hex = packet[3:3 + bytecount].hex()
            log(f"response slave={slave} fc={fc} bytes={bytecount} data={data_hex}")

    # Exception response:
    # nicht mehr einzeln loggen, damit die Konsole ruhig bleibt
    elif fc & 0x80 and len(packet) == 5:
        pass

    return packet


# --------------------------------------------------
# Start
# --------------------------------------------------
async def main():
    # PyModbus-Fehlerausgaben unterdrücken, damit bei absichtlich
    # ausgelöster ModbusException nicht wieder Tracebacks die
    # Konsole vollschreiben.
    logging.getLogger("pymodbus").setLevel(logging.CRITICAL)
    logging.getLogger("pymodbus.server").setLevel(logging.CRITICAL)
    logging.getLogger("pymodbus.server.requesthandler").setLevel(logging.CRITICAL)

    store = ShellySnapshotStore()
    shared_state = SharedState(store)

    poller = ShellyPoller(
        url=SHELLY_URL,
        username=SHELLY_USERNAME,
        password=SHELLY_PASSWORD,
        store=store,
        interval=SHELLY_POLL_INTERVALL,
        timeout=SHELLY_POLLTIMEOUT,
        reconnect_delay=0.2,
        log_enabled=ENABLE_LOGGING,
        on_new_snapshot=shared_state.update_from_snapshot,
    )

    values = [0] * REGISTER_COUNT
    block = KsemBlock(0, values, shared_state)
    device = GuardedDeviceContext(block, shared_state)

    context = ModbusServerContext(
        devices={SLAVE_ID: device},
        single=False,
    )


    print("Starte KSEM-Server mit Shelly-Poller")
    print(f"Serial: {SERIAL_PORT} {BAUDRATE} {BYTESIZE}{PARITY}{STOPBITS}")
    print(f"Shelly: {SHELLY_URL}")
    print("Momentanwerte nur bis Register 147, keine Register >= 500")
    print(f"Logging: {'an' if ENABLE_LOGGING else 'aus'}")
    print(f"Shelly-Timeout für Modbus-Antworten: {STALE_DATA_TIMEOUT_SECONDS:.1f} s")
    print("")

    poller_task = asyncio.create_task(poller.run_forever())

    try:
        await StartAsyncSerialServer(
            context=context,
            port=SERIAL_PORT,
            baudrate=BAUDRATE,
            bytesize=BYTESIZE,
            parity=PARITY,
            stopbits=STOPBITS,
            timeout=1,
            trace_packet=trace_packet,
        )
    finally:
        poller_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
