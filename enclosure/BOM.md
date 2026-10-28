# Parts list

Everything the box needs, and where to buy it. Two files import straight into
a distributor cart:

- `bom_digikey.csv`: DigiKey (cart or BOM Manager upload). Two rows have no
  DigiKey part number yet; the upload matches them on the manufacturer part
  number.
- `bom_mouser.csv`: Mouser (BOM tool upload).

Neither distributor carries everything: see [Buy elsewhere](#buy-elsewhere).

| Part | Qty | DigiKey | Mouser | Notes |
|---|---|---|---|---|
| Raspberry Pi Zero 2 W with header (SC0721) | 1 | [2648-SC0721-ND](https://www.digikey.com/en/products/detail/raspberry-pi/SC0721/24627135) | [358-SC0721](https://www.mouser.com/ProductDetail/358-SC0721) | Often out of stock at both; backorder or buy elsewhere. |
| microSD card | 1 | [2648-SC1628-ND](https://www.digikey.com/en/products/detail/raspberry-pi/SC1628/24627139) (32 GB) | [358-SC1629](https://www.mouser.com/ProductDetail/358-SC1629) (64 GB) | Any 8 GB+ card works. Mouser doesn't sell the 32 GB SC1628. |
| USB-C power socket (Adafruit 5993) | 1 | [1528-5993-ND](https://www.digikey.com/en/products/result?keywords=1528-5993-ND) | [485-5993](https://www.mouser.com/ProductDetail/485-5993) | |
| USB-C to micro-USB cable, 1 m (Adafruit 3878) | 1 | [1528-2704-ND](https://www.digikey.com/en/products/detail/adafruit-industries-llc/3878/9607601) | [485-3878](https://www.mouser.com/ProductDetail/485-3878) | Reader to Pi. Straight plugs fit (see the README for plug sizes). |
| USB-A to micro-USB cable, 1 m (Adafruit 592) | 1 | [Adafruit 592](https://www.digikey.com/en/products/detail/adafruit-industries-llc/592/10669955) | [485-592](https://www.mouser.com/ProductDetail/485-592) | Cut down for the power lead. Any spare micro-USB cable does, or a 1 ft 22 AWG micro-USB power lead ([Jienk 5-pack on Amazon](https://www.amazon.com/dp/B0CX1N7XGR)). |
| M3 × 4 mm heat-set inserts, 50 pack (Adafruit 4255) | 1 | [1528-4255-ND](https://www.digikey.com/en/products/result?keywords=1528-4255-ND) | [485-4255](https://www.mouser.com/ProductDetail/485-4255) | 4 used. |
| Rubber feet 11.2 × 5 mm (3M SJ-5003 black) | 4 | [SJ5003-0-ND](https://www.digikey.com/en/products/result?keywords=SJ5003-0-ND) | [517-SJ-5003BK](https://www.mouser.com/ProductDetail/517-SJ-5003BK) | Mouser sells them in pads of 56. |
| M2.5 × 16 pan head, Pi stack (Keystone 29306) | 4 | [36-29306-ND](https://www.digikey.com/en/products/detail/keystone-electronics/29306/1532986) | [534-29306](https://www.mouser.com/ProductDetail/534-29306) | Slotted, zinc-plated steel. Neither stocks M2.5 × 14 pan head in steel, so use 16 mm with the printed 2 mm washers, as the README allows. |
| M2.5 × 8 pan head, power board (APM Hexseal RM2.5X8 2701) | 4 | [RM2.5X8-2701](https://www.digikey.com/en/products/detail/apm-hexseal/RM2-5X8-2701/2743216) | [608-RM2.5X8MM2701](https://www.mouser.com/ProductDetail/608-RM2.5X8MM2701) | Stainless, Phillips. A self-sealing screw with an O-ring under the head, which is harmless here. |

## Buy elsewhere

Neither DigiKey nor Mouser carries these:

- **SeenGreat 1.3" OLED HAT.** [On Amazon](https://a.co/d/09jW1LQh). The case is shaped around this board.
- **PN532 NFC reader, USB-C (CH340).** [On Amazon](https://a.co/d/0b7JEN1F). Both
  distributors sell Adafruit's PN532 boards (364, 789), but they cost far
  more, are a different size and need a separate USB serial adapter, so they
  don't fit the reader keepers.
- **Instax Square Link printer and Instax Square film.**
- **NFC stickers, 25 mm square, on a roll.** The closest is Adafruit 4032
  (NTAG213, 40 × 25 mm, sold singly: DigiKey
  [4032](https://www.digikey.com/en/products/detail/adafruit-industries-llc/4032/9838299),
  Mouser [485-4032](https://www.mouser.com/ProductDetail/485-4032)). It works,
  but it's too wide for the sticker dispenser and costs far more per tag than
  a roll.
- **M2.5 × 20 pan head screws (2) for the reader keepers.** 16 or 18 mm
  also work, with less grip; 22 mm or longer runs past the pilot hole.
- **M3 flat-head screws, about 6 mm (4) for the base plate.** Neither stocks a
  steel M3 countersunk screw near this length.
- **A speaker.**
