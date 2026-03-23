# KSEM-Emulator für KOSTAL Plenticore

## Inhaltsverzeichnis

- [Ziel des Projekts](#ziel-des-projekts)
- [Funktionsprinzip](#funktionsprinzip)
- [Was emuliert wird – und was nicht](#was-emuliert-wird--und-was-nicht)
- [Hardware](#hardware)
- [Verdrahtung](#verdrahtung)
- [Geeignete Energiemessgeräte als Datenquelle](#geeignete-energiemessger%C3%A4te-als-datenquelle)
- [Modbus-Verhalten des Wechselrichters](#modbus-verhalten-des-wechselrichters)
- [Hintergrund zur Reaktionszeit](#hintergrund-zur-reaktionszeit)
- [Softwareaufbau](#softwareaufbau)
- [Einrichtung unter Linux](#einrichtung-unter-linux)
- [Installation als Service](#installation-als-service)
- [Service wieder entfernen](#service-wieder-entfernen)
- [Python Virtual Environment einrichten](#python-virtual-environment-einrichten)
- [Benutzung](#benutzung)
- [Logging und Statusanzeige](#logging-und-statusanzeige)
- [Verhalten bei fehlenden Shelly-Daten](#verhalten-bei-fehlenden-shelly-daten)
- [Installateurcode und wichtige Warnhinweise](#installateurcode-und-wichtige-warnhinweise)
- [Danksagung und persönliche Anmerkung](#danksagung-und-pers%C3%B6nliche-anmerkung)
- [Erweiterbarkeit](#erweiterbarkeit)
- [Verwendete Dokumentation und Quellen](#verwendete-dokumentation-und-quellen)

---

## Ziel des Projekts

Ziel dieses Projekts ist es, ein KSEM-Energiemeter für einen KOSTAL-Wechselrichter zu emulieren. Damit kann man einen Kostal Wechselrichter mit Akku betreiben. Durch die Emulation eines KSEM werden am meisten Wechselrichter von Kostal unterstützt und auch die meisten Konfigurationen. Die aktuellste Version der [Freigegebenen Energiezähler](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/Listen/Freigegebene-Energiezaehler.pdf) ist von Dezember 2025. Laut dieser werden vom KSEM unterstützt:
* PIKO IQ X
* PLENTICORE BI
* PLENTICORE plus
* PLENTICORE BI G2
* PLENTICORE plus G2
* PLENTICORE G3
* PLENTICORE MP G3

Bei 
* PIKO CI 
* PIKO EPC
* PIKO 4.2-20 

heißt es im Dokument:

> Einstellungen am Wechselrichter sind nicht notwendig. Alle Einstellungen werden im KOSTAL Smart Energy Meter durchgeführt.

Hier könnte es sein, dass das Kostal Energy-Meter als Master auftritt und die Daten an den Wechselrichter schickt und daher dieses Projekt erst nach einem Umbau für diese Wechselrichter funktionieren kann. Entwickelt und getestet wurde dieses Projekt mit einem Kostal Plenticore Plus G2 Wechselrichter.


Es werden bewusst nur die Werte emuliert, die unbedingt notwendig sind, damit der Wechselrichter mit dem emulierten Gerät zusammenarbeitet. Es geht also nicht darum, ein vollständiges KSEM in allen Funktionen nachzubauen, sondern genau die für den praktischen Betrieb relevanten Register und Zustände bereitzustellen.

Die Emulation wurde mit Hilfe der offiziellen KOSTAL-Dokumentation nachgebildet:  
[KOSTAL Interface KSEM – Registerbeschreibung](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/BA_KOSTAL_Interface_KSEM_DE.pdf)

---

## Funktionsprinzip

Der Wechselrichter kommuniziert per Modbus RTU über RS485 mit einem Messgerät. Dieses Projekt übernimmt die Rolle des KSEM und beantwortet die Modbus-Anfragen des Wechselrichters.

Als Datenquelle dienen dabei Messwerte eines externen Energiemessgeräts, aktuell insbesondere eines Shelly 3EM. Diese Werte werden in das von KOSTAL erwartete Registerformat umgerechnet und dem Wechselrichter so präsentiert, als ob ein echtes KSEM angeschlossen wäre.

Das Projekt besteht damit logisch aus zwei Teilen:

1. einem Eingang, der aktuelle Leistungsdaten beschafft
2. einem Modbus-Server, der daraus KSEM-kompatible Register bereitstellt

Im aktuellen Zustand werden als Eingang Shelly-Daten verwendet. Theoretisch ist das Ganze aber modular. Man kann also auch andere Geräte als den Shelly als Input liefern. Wenn man bereits ein Energiemeter eines anderen Herstellers hat, kann man die Software entsprechend erweitern.

---

## Was emuliert wird – und was nicht

Es werden nur die Register und Werte emuliert, die der Wechselrichter für die Zusammenarbeit offensichtlich benötigt.

Sobald der Wechselrichter auf Register 8244 eine gültige Antwort erhält, beginnt er aktuelle Leistungsdaten abzufragen. Die nachfolgenden Register bis 8249 werden zwar ebenfalls emuliert, wurden aber während des Loggings nicht aktiv abgefragt.

Die eigentlichen Momentanwerte werden in den relevanten Leistungsregistern bereitgestellt. Register ab 500 werden in diesem Projekt bewusst nicht verwendet, weil es hier nur um die für die Zusammenarbeit notwendigen aktuellen Leistungsdaten geht.

---

## Hardware

Als Hardware kann man einen Raspberry Pi 3 verwenden. Es sollte aber auch ein Raspberry Pi Zero 2 W ausreichen. Es gibt USB-Hubs, an denen man gleichzeitig einen RS485-Adapter und einen LAN-Anschluss integriert kann. 


---

## Verdrahtung

Die RS485-Verdrahtung ist unkompliziert:

- A auf A
- B auf B

Zusätzlich wird ein GND-Anschluss verwendet.

Als Kabel hat sich EIB/KNX-Busleitung `J-Y(ST) Yh 2x2x0,8` als tauglich erwiesen. Für den GND-Anschluss hat in meinen Tests sogar der dünne Massedraht gereicht. Da mit vier Adern aber ohnehin ausreichend Material vorhanden ist, kann man natürlich auch problemlos eine vollwertige Ader für GND verwenden.

---

## Geeignete Energiemessgeräte als Datenquelle

Der große Vorteil der Shellys ist, dass sie nur eine Teilungseinheit benötigen, während klassische Energiemessgeräte oft vier Teilungseinheiten belegen und je nach Platz im Zählerschrank deutlich aufwendiger anzuschließen sind. Die Messspulen des Shelly lassen sich flexibler anbringen.


### Shelly Pro 3EM

Der Shelly Pro 3EM erscheint auf den ersten Blick besonders geeignet, weil er eine stabilere Netzwerkverbindung per LAN-Kabel hat.

Allerdings hat der Shelly Pro 3EM einen entscheidenden Nachteil: Er liefert neue Werte nur etwa jede Sekunde.Dazu gibt es auch einen passenden Hinweis aus der Shelly-Community:  
[Suggestion: higher measurement interval for Shelly 3EM Pro](https://community.shelly.cloud/topic/10428-suggestion-higher-measurement-interval-for-shelly-3em-pro-any-generation/)

### Shelly 3EM

Der ältere Shelly 3EM wird nur per WLAN angeschlossen. Das kann einerseits ein Nachteil sein, andererseits aber auch ein Vorteil, weil kein zusätzliches Netzwerkkabel verlegt werden muss.

Vor allem aber liefert der ältere Shelly 3EM neue Daten mit etwa 0,5 Sekunden Abstand und reagiert damit ungefähr doppelt so schnell wie die neuere Pro-Variante. Um die Daten möglichst aktuell zu haben, wird er alle 100 Millisekunden ab. Ich habe versucht, das Ganze ausgeklügelter zu machen und mit weniger Abfragen auszukommen, aber dann besteht das Risiko, ältere Daten zu erwischen. Das Abfrageintervall von 100 Millisekunden hat er in meinen Tests problemlos verkraftet.

---

## Modbus-Verhalten des Wechselrichters

Nach meinen Logs fragt der Wechselrichter die aktuellen Leistungsdaten im Abstand von ungefähr 160 Millisekunden ab.

Das ist bemerkenswert, weil wir im Register 8244 eine Mess- beziehungsweise Aktualisierungsrate von 500 Millisekunden angeben. Der Wechselrichter scheint diesen Wert also nicht wirklich zur zeitlichen Steuerung seiner Abfragen zu verwenden. Nach meinem Eindruck dient dieser Registerinhalt nur dazu, dass der Wechselrichter erkennt, dass tatsächlich ein KSEM angeschlossen ist.

Praktisch bedeutet das:

- Der Wechselrichter beginnt nach erfolgreicher Erkennung des KSEM sofort mit der Abfrage der Momentanwerte.
- Er fragt diese Werte danach deutlich schneller ab, als es der nominelle Messintervallwert vermuten lässt.
- Der tatsächlich beobachtete Abstand liegt bei etwa 160 Millisekunden.

---

## Hintergrund zur Reaktionszeit

Das originale KSEM misst wohl alle 200 oder 500 Millisekunden, wie diese Dokumentation nahelegt:  
[KOSTAL Smart Energy Meter / Betriebsanleitung](https://documents.kostal.com/KSEM-G1/BA/de-DE/83583371.html)

Wichtig ist dabei aber ein Unterschied: Dort ist von „Senden“ die Rede. Das gilt nur für den Modbus-Master-Modus des Geräts. Wenn das Gerät an einem Plenticore-Wechselrichter hängt, läuft es im Slave-Modus, und der Wechselrichter ist der Master, der das KSEM abfragt.

In der [HTW Stromspeicher-Inspektion 2025](https://solar.htw-berlin.de/wp-content/uploads/HTW-Stromspeicher-Inspektion-2025.pdf) wurde bei KOSTAL eine Reaktionszeit von 0,4 Sekunden gemessen. Leider wurde dort nicht angegeben, welches konkrete Leistungsmessgerät von KOSTAL verwendet wurde. Außerdem ist zu beachten, dass sich die Regelung damit noch nicht vollständig eingeschwungen hatte. Laut den dort gezeigten Werten dauerte es weitere 2,2 Sekunden, bis das System endgültig eingeschwungen war, also insgesamt etwa 2,6 Sekunden.

Für schnell taktende Lasten wie Induktionsherde ist das natürlich zu träge. In solchen Fällen wird dann zwangsläufig für gewisse Zeit Leistung aus dem Netz bezogen oder unnötig eingespeist. Glücklicherweise ziehen Induktionsherde auf höheren Leistungsstufen meist konstant, sodass dieser Pulsbetrieb vor allem auf niedrigeren Stufen relevant ist. Bei Bosch- und Siemens-Geräten liegt dieser Bereich nach meiner Beobachtung ungefähr bei Stufe 6 oder 6,5.

---

## Softwareaufbau

Die Software emuliert einen KSEM-Modbus-Slave und berechnet daraus die benötigten Registerwerte.

Dazu gehören insbesondere:

- Wirkleistung Bezug und Einspeisung
- Blindleistung
- Scheinleistung
- Strom
- Spannung
- Leistungsfaktor
- Frequenz
- Erkennungsregister des KSEM

Ein Teil dieser Werte kommt direkt vom Eingangsgerät, ein Teil wird aus den vorhandenen Messwerten berechnet.

Logging kann aktiviert oder deaktiviert werden. Außerdem wird auf der Konsole ein Status angezeigt, sodass man sieht, ob das Skript noch läuft und ob aktuelle Daten vom Eingangsgerät vorhanden sind.

---

## Einrichtung unter Linux

Zunächst sollte der Benutzer Zugriff auf das serielle Gerät bekommen. Dafür muss einmalig folgendes ausgeführt werden:

```bash
sudo usermod -aG dialout $USER
```

Danach muss man sich einmal ausloggen und wieder einloggen, damit die Gruppenänderung wirksam wird.

Ohne diesen Schritt kann es sein, dass der Zugriff auf `/dev/ttyUSB0` bzw. ein ähnliches serielles Gerät verweigert wird.

---

## Python Virtual Environment einrichten

Ein Python Virtual Environment einzurichten ist sinnvoll, damit die benötigten Pakete sauber und getrennt vom restlichen System installiert werden.

Beispiel:

```bash
python3 -m venv .ksemServer
source .ksemServer/bin/activate
pip install --upgrade pip
pip install pymodbus httpx pyserial
```
---

### Installation als Service

Damit der `ksemServer` beim Systemstart automatisch gestartet wird, kann er als `systemd`-Dienst installiert werden.

Zunächst das Installationsskript ausführbar machen:

```bash
chmod +x DienstInstallieren.sh
```

Danach den Dienst installieren und starten:

```bash
sudo ./DienstInstallieren.sh
```

---

### Service wieder entfernen

Wenn der Dienst wieder entfernt werden soll, empfiehlt sich folgende Reihenfolge:

Zuerst den Dienst stoppen und deaktivieren:

```bash
sudo systemctl stop ksem.service
sudo systemctl disable ksem.service
```

Dann die Service-Datei löschen:

```bash
sudo rm /etc/systemd/system/ksem.service
```

Anschließend `systemd` neu einlesen:

```bash
sudo systemctl daemon-reload
```

## Benutzung

Vor der Benutzung müssen im Skript mindestens diese Dinge angepasst werden:

- die IP-Adresse des Shelly
- [Benutzername ist meines Wissens immer admin]
- das Passwort
- gegebenenfalls der serielle Port des RS485-Adapters

Typischerweise also zum Beispiel:

- `SHELLY_URL = "http://192.168.178.x/status"`
- `SHELLY_USERNAME = "admin"`
- `SHELLY_PASSWORD = "..."`

Danach kann das Skript einfach gestartet werden:

```bash
python3 ksemServer.py
```

Der Wechselrichter muss dann so konfiguriert werden, dass er ein KSEM über RS485 erwartet. Diese geht unter Service --> Allgemein --> Netzanschluss und dort "KOSTAL Smart Energy Meter (KSEM)" wählen und der Einbauort ist wohl Netzanschlusspunkt, wenn der Shelly unmittelbar hinter dem Zähler angebracht ist und der Strom von dort weiter ins Haus und zum Wechselrichter geht.

---

## Logging und Statusanzeige

Im Skript gibt es einen Schalter, mit dem Logging aktiviert oder deaktiviert werden kann.

Wenn Logging aktiv ist, werden unter anderem Modbus-Requests und Responses sowie Shelly-Abfragen angezeigt. Das ist beim Debugging sehr hilfreich.

Zusätzlich gibt es eine Statusanzeige auf der Konsole. Damit sieht man, ob:

- der KSEM-Server läuft
- aktuelle Shelly-Daten vorhanden sind
- aktuell keine frischen Daten vorliegen

So kann man auch bei reduziertem Logging erkennen, dass das Skript noch arbeitet.

---

## Verhalten bei fehlenden Shelly-Daten

Das ist einer der wichtigsten Sicherheitsmechanismen des Projekts.

Wenn die Daten des Shelly älter als fünf Sekunden sind, antwortet das emulierte Gerät nicht mehr mit normalen Modbus-Werten. Der Wechselrichter erkennt dann eine Störung bzw. Unterbrechung am/zum Messgerät.

Genau dieses Verhalten ist beabsichtigt. Es soll ausdrücklich verhindert werden, dass veraltete oder falsche Leistungsdaten weitergemeldet werden. Denn das könnte dazu führen, dass falsch eingespeist wird oder der Akku falsch geladen beziehungsweise entladen wird.

Es ist viel besser, wenn der Wechselrichter in diesem Fall gar keine gültigen Leistungswerte mehr bekommt und stattdessen einen Fehler erkennt. Dann zeigt er eben keine Leistung mehr an, statt einer falschen. Letzteres wäre deutlich problematischer.

---

## Hardware für die RS485-Anbindung

Ich habe diesen Konverter verwendet, weil er galvanisch isoliert ist:  
[Waveshare USB-zu-RS485/422 isolierter Konverter, integrierter FT232RL und SP485EEN](https://de.aliexpress.com/item/1005009718898858.html)

Er hat eine Leerlaufleistungsaufnahme von 0,22 Watt. Diese Leistungsaufnahme wurde im Leerlauf direkt am USB-Anschluss gemessen, also ohne Netzteilverluste.

Es sollte aber auch dieser günstigere Adapter funktionieren:  
[Waveshare Industrieller USB-zu-RS485-Konverter](https://de.aliexpress.com/item/1005009682263550.html)

Dieser hat im Leerlauf keine messbare Leistungsaufnahme gezeigt.


---

## Installateurcode und wichtige Warnhinweise

Um das Messgerät im KOSTAL-System passend einzustellen, braucht man einen KOSTAL-Installateurcode.

Der Code lautet:

`RKYEBWWC`

Diesen Code hat mir freundlicherweise jemand im Photovoltaik-Forum mit der ausdrücklichen Erlaubnis zur Verfügung gestellt, ihn weiterzugeben.

Mit diesem Code sollte man vorsichtig umgehen und nur die Einstellungen ändern, die für Akku und Messgerät wirklich notwendig sind. Man kann damit nämlich auch Netzparameter verändern, und davon sollte man die Finger lassen, wenn man nicht genau weiß, was man tut.

Anders gesagt: Man zerlegt ja auch keinen Automotor in der Hoffnung, dass er danach mehr Leistung hat und genauso lange hält, man keine Ahnung davon hat.

---

## Danksagung und persönliche Anmerkung

Es war leider ziemlich frustrierend zu erleben, auf wie wenig Unterstützung ich bei diesem Thema gestoßen bin. Teilweise wurde das ganze Projekt sogar grundsätzlich in Abrede gestellt.

Zum Glück gibt es aber auch sehr hilfsbereite Menschen. Einige haben sich per persönlicher Nachricht gemeldet, mich unterstützt und ihre Hilfe angeboten. Dafür bedanke ich mich sehr herzlich. Ohne diese Unterstützung wäre dieses Projekt wohl niemals möglich geworden.

Leider tun sich in diesem Bereich auch unschöne Abgründe auf. Mir wurde angeboten, Einstellungen per TeamViewer an meinem Wechselrichter zu ändern. Für diesen Einsatz von vielleicht fünf Minuten hätte ich 70 Euro bezahlen sollen. Das halte ich für Wucher.

Möge dieser öffentliche Code dazu beitragen, dass dieser Sumpf austrocknet, in dem sich manche auf unangemessene Weise bereichern. Ein Nutzer hat mir den Code gerade deshalb nicht gegeben, weil er befürchtete, ich könnte damit später selbst anfangen, anderen dafür Geld abzunehmen. Ich hoffe sehr, dass dieses Geschäftsmodell durch offen verfügbaren Code an Boden verliert.

---

## Erweiterbarkeit

Auch wenn dieses Projekt aktuell auf den Shelly 3EM als Datenquelle zugeschnitten ist, ist die grundsätzliche Struktur modular.

Das bedeutet:

- Andere Messgeräte können grundsätzlich ebenfalls als Eingang verwendet werden.
- Wer bereits ein Energiemeter eines anderen Herstellers besitzt, kann die Software entsprechend erweitern.
- Entscheidend ist nur, dass am Ende die für den Wechselrichter benötigten KSEM-Register korrekt befüllt werden.

Gerade weil der Wechselrichter anscheinend nur einen relativ kleinen Teil des gesamten KSEM-Funktionsumfangs wirklich aktiv nutzt, ist dieser Ansatz praktisch und gut beherrschbar.

---

## Verwendete Dokumentation und Quellen

KOSTAL freigebenen Energiezähler:
[https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/Listen/Freigegebene-Energiezaehler.pdf]

KOSTAL KSEM-Registerbeschreibung:  
[https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/BA_KOSTAL_Interface_KSEM_DE.pdf](https://www.kostal-solar-electric.com/fileadmin/downloadcenter/kse/BA_KOSTAL_Interface_KSEM_DE.pdf)

KOSTAL KSEM Dokumentation / Messintervall-Hinweis:  
[https://documents.kostal.com/KSEM-G1/BA/de-DE/83583371.html](https://documents.kostal.com/KSEM-G1/BA/de-DE/83583371.html)

HTW Stromspeicher-Inspektion 2025:  
[https://solar.htw-berlin.de/wp-content/uploads/HTW-Stromspeicher-Inspektion-2025.pdf](https://solar.htw-berlin.de/wp-content/uploads/HTW-Stromspeicher-Inspektion-2025.pdf)

Shelly-Community zur Aktualisierungsrate des Shelly Pro 3EM:  
[https://community.shelly.cloud/topic/10428-suggestion-higher-measurement-interval-for-shelly-3em-pro-any-generation/](https://community.shelly.cloud/topic/10428-suggestion-higher-measurement-interval-for-shelly-3em-pro-any-generation/)

Isolierter Waveshare USB-RS485-Adapter:  
[https://de.aliexpress.com/item/1005009718898858.html](https://de.aliexpress.com/item/1005009718898858.html)

Günstiger Waveshare USB-RS485-Adapter:  
[https://de.aliexpress.com/item/1005009682263550.html](https://de.aliexpress.com/item/1005009682263550.html)
