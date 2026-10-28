from enum import StrEnum


class PrinterRole(StrEnum):
    KITCHEN = "kitchen"  # receives KOTs (no prices)
    COUNTER = "counter"  # receives customer bills


class PrinterConnection(StrEnum):
    USB = "usb"
    LAN = "lan"
    BLUETOOTH = "bluetooth"
    SYSTEM = "system"  # an OS print queue (Windows spooler / CUPS), sent raw


class JobKind(StrEnum):
    TICKET = "ticket"
    BILL = "bill"
    TEST = "test"


class JobStatus(StrEnum):
    QUEUED = "queued"
    SENT = "sent"
    PRINTED = "printed"
    FAILED = "failed"
