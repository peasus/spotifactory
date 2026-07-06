#!/usr/bin/env python3

from math import ceil
from struct import pack, unpack_from
from time import sleep

try:
    from .Types import EventType, InfoType, PrinterSettings
    from . import LedPatterns
except ImportError:
    from Types import EventType, InfoType, PrinterSettings
    import LedPatterns

import argparse
import simplepyble
import sys
from PIL import Image
from io import BytesIO


class InstaxBLE:
    def __init__(
        self,
        device_address=None,
        device_name=None,
        print_enabled=False,
        dummy_printer=False,
        verbose=False,
        quiet=False,
        image_path=None):

        self.serviceUUID = '70954782-2d83-473d-9e5f-81e1d02d5273'
        self.writeCharUUID = '70954783-2d83-473d-9e5f-81e1d02d5273'
        self.notifyCharUUID = '70954784-2d83-473d-9e5f-81e1d02d5273'
        self.peripheral = None

        self.quiet = quiet
        self.dummyPrinter = dummy_printer
        self.printerSettings = PrinterSettings['mini'] if self.dummyPrinter else None
        self.chunkSize = PrinterSettings['mini']['chunkSize'] if self.dummyPrinter else 0
        self.printEnabled = print_enabled
        self.deviceName = device_name.upper() if device_name else None
        self.deviceAddress = device_address.upper() if device_address else None
        self.image_path = image_path
        self.verbose = verbose if not self.quiet else False
        self.packetsForPrinting = []
        self.pos = (0, 0, 0, 0)
        self.batteryState = 0
        self.batteryPercentage = 0
        self.photosLeft = 0
        self.isCharging = False
        self.imageSize = (PrinterSettings['mini']['width'], PrinterSettings['mini']['height']) if self.dummyPrinter else (0, 0)
        self.waitingForResponse = False
        self.cancelled = False

        adapters = simplepyble.Adapter.get_adapters()
        if len(adapters) == 0:
            if not self.quiet:
                sys.exit("No bluetooth adapters found (are they enabled?)")
            else:
                sys.exit()

        if len(adapters) > 1:
            self.log(f"Found multiple adapters: {', '.join([adapter.identifier() for adapter in adapters])}")
            self.log(f"Using the first one: {adapters[0].identifier()}")
        self.adapter = adapters[0]

    def log(self, msg):
        if self.verbose:
            print(msg)

    def display_current_status(self):
        print("\nPrinter details: ")
        print(f"Model:               {self.printerSettings['modelName']}")
        print(f"Photos left:         {self.photosLeft}/10")
        print(f"Battery level:       {self.batteryPercentage}%")
        print(f"Charging:            {self.isCharging}")
        print(f"Required image size: {self.printerSettings['width']}x{self.printerSettings['height']}px")
        if self.peripheral.mtu:
            print(f"MTU:                 {self.peripheral.mtu()}")
        print("")

    def parse_printer_response(self, event, packet):
        self.waitingForResponse = False

        if event == EventType.XYZ_AXIS_INFO:
            x, y, z, o = unpack_from('<hhhB', packet[6:-1])
            self.pos = (x, y, z, o)
        elif event == EventType.LED_PATTERN_SETTINGS:
            pass
        elif event == EventType.SUPPORT_FUNCTION_INFO:
            try:
                infoType = InfoType(packet[7])
            except ValueError:
                self.log(f'Unknown InfoType: {packet[7]}')
                return

            if infoType == InfoType.IMAGE_SUPPORT_INFO:
                w, h = unpack_from('>HH', packet[8:12])
                self.imageSize = (w, h)
                if (w, h) == (600, 800):
                    self.printerSettings = PrinterSettings['mini']
                elif (w, h) == (800, 800):
                    self.printerSettings = PrinterSettings['square']
                elif (w, h) == (1260, 840):
                    self.printerSettings = PrinterSettings['wide']
                else:
                    exit(f'Unknown image size from printer: {w}x{h}')
                self.chunkSize = self.printerSettings['chunkSize']

            elif infoType == InfoType.BATTERY_INFO:
                self.batteryState, self.batteryPercentage = unpack_from('>BB', packet[8:10])
            elif infoType == InfoType.PRINTER_FUNCTION_INFO:
                dataByte = packet[8]
                self.photosLeft = dataByte & 15
                self.isCharging = (1 << 7) & dataByte >= 1

        elif event == EventType.PRINT_IMAGE_DOWNLOAD_START:
            self.handle_image_packet_queue()
        elif event == EventType.PRINT_IMAGE_DOWNLOAD_DATA:
            self.handle_image_packet_queue()
        elif event == EventType.PRINT_IMAGE_DOWNLOAD_END:
            self.handle_image_packet_queue()
        elif event == EventType.PRINT_IMAGE_DOWNLOAD_CANCEL:
            pass
        elif event == EventType.PRINT_IMAGE:
            self.log('received print confirmation')
        else:
            self.log(f'Uncaught response from printer. Eventype: {event}')

    def handle_image_packet_queue(self):
        if len(self.packetsForPrinting) > 0 and not self.cancelled:
            if len(self.packetsForPrinting) % 10 == 0:
                self.log(f"Img packets left to send: {len(self.packetsForPrinting)}")
            packet = self.packetsForPrinting.pop(0)
            self.send_packet(packet)

    def notification_handler(self, packet):
        if not self.quiet:
            if len(packet) < 8:
                self.log(f"\tError: response packet size should be >= 8 (was {len(packet)})!")
                return
            elif not self.validate_checksum(packet):
                self.log("\tResponse packet checksum was invalid!")
                return

        header, length, op1, op2 = unpack_from('>HHBB', packet)
        try:
            event = EventType((op1, op2))
        except ValueError:
            self.log(f"Unknown EventType: ({op1}, {op2})")
            return

        self.parse_printer_response(event, packet)

    def connect(self, timeout=0):
        if self.dummyPrinter:
            return

        self.peripheral = self.find_device(timeout=timeout)
        if self.peripheral:
            try:
                self.log(f"Connecting to {self.peripheral.identifier()} [{self.peripheral.address()}]")
                self.peripheral.connect()
            except Exception as e:
                if not self.quiet:
                    self.log(f'error on connecting: {e}')

            if self.peripheral.is_connected():
                self.log("Connected")
                try:
                    self.peripheral.notify(self.serviceUUID, self.notifyCharUUID, self.notification_handler)
                except Exception as e:
                    if not self.quiet:
                        self.log(f'Error on attaching notification_handler: {e}')
                        return

                self.get_printer_info()
                sleep(1)
                self.display_current_status()

    def disconnect(self):
        if self.dummyPrinter:
            return
        if self.peripheral:
            if self.peripheral.is_connected():
                self.log('Disconnecting...')
                self.peripheral.disconnect()
                self.log("Disconnected")

    def cancel_print(self):
        self.packetsForPrinting = []
        self.waitingForResponse = False
        self.send_packet(self.create_packet(EventType.PRINT_IMAGE_DOWNLOAD_CANCEL))

    def enable_printing(self):
        self.printEnabled = True

    def disable_printing(self):
        self.printEnabled = False

    def find_device(self, timeout=0):
        self.log('Searching for instax printer...')
        secondsTried = 0
        try:
            while True:
                self.adapter.scan_for(2000)
                peripherals = self.adapter.scan_get_results()
                # Prefer (ANDROID) over (IOS) — on Linux/BlueZ the ANDROID
                # advertisement address connects reliably; IOS aborts locally.
                peripherals = sorted(
                    peripherals,
                    key=lambda p: 0 if p.identifier().endswith('(ANDROID)') else 1,
                )
                for peripheral in peripherals:
                    foundName = peripheral.identifier()
                    foundAddress = peripheral.address()
                    if (self.deviceName and foundName.startswith(self.deviceName)) or \
                       (self.deviceAddress and foundAddress == self.deviceAddress) or \
                       (self.deviceName is None and self.deviceAddress is None and
                       foundName.startswith('INSTAX-')):
                        if peripheral.is_connectable():
                            return peripheral
                        elif not self.quiet:
                            self.log(f"Can't connect to printer at {foundAddress}")
                secondsTried += 2
                if timeout != 0 and secondsTried >= timeout:
                    return None
        except KeyboardInterrupt:
            self.cancel_print()
            self.disconnect()
            sys.exit()

    def create_color_payload(self, colorArray, speed, repeat, when):
        payload = pack('BBBB', when, len(colorArray), speed, repeat)
        for color in colorArray:
            payload += pack('BBB', color[0], color[1], color[2])
        return payload

    def send_led_pattern(self, pattern, speed=5, repeat=255, when=0):
        payload = self.create_color_payload(pattern, speed, repeat, when)
        packet = self.create_packet(EventType.LED_PATTERN_SETTINGS, payload)
        self.send_packet(packet)

    def prettify_bytearray(self, value):
        return ' '.join([f'{x:02x}' for x in value])

    def create_checksum(self, bytearray):
        return (255 - (sum(bytearray) & 255)) & 255

    def create_packet(self, eventType, payload=b''):
        if isinstance(eventType, EventType):
            eventType = eventType.value

        header = b'\x41\x62'
        opCode = bytes([eventType[0], eventType[1]])
        packetSize = pack('>H', 7 + len(payload))
        packet = header + packetSize + opCode + payload
        packet += pack('B', self.create_checksum(packet))
        return packet

    def validate_checksum(self, packet):
        return (sum(packet) & 255) == 255

    def send_packet(self, packet):
        if not self.dummyPrinter and not self.quiet:
            if not self.peripheral:
                self.log("no peripheral to send packet to")
            elif not self.peripheral.is_connected():
                self.log("peripheral not connected")

        try:
            while self.waitingForResponse and not self.dummyPrinter and not self.cancelled:
                sleep(0.05)

            header, length, op1, op2 = unpack_from('>HHBB', packet)
            try:
                event = EventType((op1, op2))
            except Exception:
                event = 'Unknown event'

            self.waitingForResponse = True
            smallPacketSize = 182
            numberOfParts = ceil(len(packet) / smallPacketSize)
            for subPartIndex in range(numberOfParts):
                subPacket = packet[subPartIndex * smallPacketSize:subPartIndex * smallPacketSize + smallPacketSize]
                if not self.dummyPrinter:
                    self.peripheral.write_command(self.serviceUUID, self.writeCharUUID, subPacket)

        except KeyboardInterrupt:
            self.cancelled = True
            self.cancel_print()
            self.disconnect()
            sys.exit('Cancelled')

    def print_image(self, imgSrc):
        self.log(f'printing image "{imgSrc}"')
        if self.photosLeft == 0 and not self.dummyPrinter:
            self.log("Can't print: no photos left")
            return

        imgData = imgSrc
        if isinstance(imgSrc, str):
            image = Image.open(imgSrc)
            imgData = self.pil_image_to_bytes(image, max_size_kb=105)
        elif isinstance(imgSrc, BytesIO):
            imgSrc.seek(0)
            image = Image.open(imgSrc)
            imgData = self.pil_image_to_bytes(image, max_size_kb=105)

        self.packetsForPrinting = [
            self.create_packet(EventType.PRINT_IMAGE_DOWNLOAD_START, b'\x02\x00\x00\x00' + pack('>I', len(imgData)))
        ]

        imgDataChunks = [imgData[i:i + self.chunkSize] for i in range(0, len(imgData), self.chunkSize)]
        if len(imgDataChunks[-1]) < self.chunkSize:
            imgDataChunks[-1] = imgDataChunks[-1] + bytes(self.chunkSize - len(imgDataChunks[-1]))

        for index, chunk in enumerate(imgDataChunks):
            imgDataChunks[index] = pack('>I', index) + chunk
            self.packetsForPrinting.append(self.create_packet(EventType.PRINT_IMAGE_DOWNLOAD_DATA, imgDataChunks[index]))

        self.packetsForPrinting.append(self.create_packet(EventType.PRINT_IMAGE_DOWNLOAD_END))

        if self.printEnabled:
            self.packetsForPrinting.append(self.create_packet(EventType.PRINT_IMAGE))
            self.packetsForPrinting.append(self.create_packet((0, 2), b'\x02'))
        elif not self.quiet:
            self.log("Printing is disabled, sending all packets except the actual print command")

        if not self.dummyPrinter:
            packet = self.packetsForPrinting.pop(0)
            self.send_packet(packet)

    def get_printer_orientation(self):
        packet = self.create_packet(EventType.XYZ_AXIS_INFO)
        self.send_packet(packet)

    def get_printer_status(self):
        packet = self.create_packet(EventType.SUPPORT_FUNCTION_INFO, pack('>B', InfoType.PRINTER_FUNCTION_INFO.value))
        self.send_packet(packet)

    def get_printer_info(self):
        packet = self.create_packet(EventType.SUPPORT_FUNCTION_INFO, pack('>B', InfoType.IMAGE_SUPPORT_INFO.value))
        self.send_packet(packet)
        packet = self.create_packet(EventType.SUPPORT_FUNCTION_INFO, pack('>B', InfoType.BATTERY_INFO.value))
        self.send_packet(packet)
        self.get_printer_status()

    def pil_image_to_bytes(self, img: Image.Image, max_size_kb: int = None) -> bytearray:
        img_buffer = BytesIO()
        if img.mode == 'RGBA':
            img = img.convert('RGB')
        img = img.resize(self.imageSize, Image.Resampling.LANCZOS)

        def save_img_with_quality(quality):
            img_buffer.seek(0)
            img_buffer.truncate(0)
            img.save(img_buffer, format='JPEG', quality=quality)
            return img_buffer.tell() / 1024

        if max_size_kb is not None:
            low_quality, high_quality = 1, 100
            current_quality = 75
            closest_quality = current_quality
            min_target_size_kb = max_size_kb * 0.9

            while low_quality <= high_quality:
                output_size_kb = save_img_with_quality(current_quality)
                if output_size_kb <= max_size_kb and output_size_kb >= min_target_size_kb:
                    closest_quality = current_quality
                    break
                if output_size_kb > max_size_kb:
                    high_quality = current_quality - 1
                else:
                    low_quality = current_quality + 1
                current_quality = (low_quality + high_quality) // 2
                closest_quality = current_quality

            save_img_with_quality(closest_quality)
            self.log(f'Saved img with quality of {closest_quality}')
        else:
            img.save(img_buffer, format='JPEG')

        return bytearray(img_buffer.getvalue())

    def wait_one_minute(self):
        if not self.quiet:
            print("Waiting for one minute...")
        sleep(60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-a', '--device-address')
    parser.add_argument('-n', '--device-name')
    parser.add_argument('-p', '--print-enabled', action='store_true')
    parser.add_argument('-d', '--dummy-printer', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    parser.add_argument('-q', '--quiet', action='store_true')
    parser.add_argument('-i', '--image-path')
    args = parser.parse_args()

    instax = InstaxBLE(**vars(args))
    try:
        instax.connect()
        if instax.image_path:
            instax.print_image(instax.image_path)
        instax.wait_one_minute()
    except Exception as e:
        print(type(e).__name__, e)
    finally:
        instax.disconnect()
