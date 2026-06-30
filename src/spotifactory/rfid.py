import ndef
import nfc

PORT = "tty:usbserial-210"


def read_card(port: str = PORT) -> dict | None:
    """Block until a card is scanned. Returns dict with uid and uri (if written)."""
    result = []

    def on_connect(tag):
        entry = {"uid": tag.identifier.hex().upper()}
        if tag.ndef and tag.ndef.records:
            for record in tag.ndef.records:
                if isinstance(record, ndef.UriRecord):
                    entry["uri"] = record.uri
                    break
        result.append(entry)
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect})

    return result[0] if result else None


def write_uri(uri: str, port: str = PORT) -> str | None:
    """Write a URI to the next scanned tag. Returns the tag UID on success."""
    result = []

    def on_connect(tag):
        if not tag.ndef:
            print("Tag is not NDEF formatted — cannot write.")
            return False
        tag.ndef.records = [ndef.UriRecord(uri)]
        result.append(tag.identifier.hex().upper())
        return False

    with nfc.ContactlessFrontend(port) as clf:
        clf.connect(rdwr={"on-connect": on_connect})

    return result[0] if result else None


if __name__ == "__main__":
    import sys

    if len(sys.argv) == 2:
        uri = sys.argv[1]
        print(f"Scan a tag to write: {uri}")
        uid = write_uri(uri)
        if uid:
            print(f"Written to tag UID: {uid}")
    else:
        print(f"Listening on {PORT} — scan a card...")
        card = read_card()
        if card:
            print(f"UID: {card['uid']}")
            if "uri" in card:
                print(f"URI: {card['uri']}")
            else:
                print("(no NDEF data written)")
