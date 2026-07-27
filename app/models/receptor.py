from datetime import datetime, timezone
from typing import Optional


class ReceivedECF:
    def __init__(self, id: str = "", sender_rnc: str = "", sender_name: str = "",
                 receiver_rnc: str = "", encf: str = "", ecf_type: str = "",
                 xml_content: str = "", arecf_xml: str = "",
                 status: str = "recibido", received_at: Optional[str] = None,
                 track_id: str = "", **kwargs):
        self.id = id
        self.sender_rnc = sender_rnc
        self.sender_name = sender_name
        self.receiver_rnc = receiver_rnc
        self.encf = encf
        self.ecf_type = ecf_type
        self.xml_content = xml_content
        self.arecf_xml = arecf_xml
        self.status = status
        self.received_at = received_at or datetime.now(timezone.utc).isoformat()
        self.track_id = track_id

    def to_dict(self):
        return {
            "sender_rnc": self.sender_rnc,
            "sender_name": self.sender_name,
            "receiver_rnc": self.receiver_rnc,
            "encf": self.encf,
            "ecf_type": self.ecf_type,
            "xml_content": self.xml_content,
            "arecf_xml": self.arecf_xml,
            "status": self.status,
            "received_at": self.received_at,
            "track_id": self.track_id,
        }

    @staticmethod
    def from_dict(id: str, data: dict):
        return ReceivedECF(id=id, **data)


class ReceivedApproval:
    def __init__(self, id: str = "", sender_rnc: str = "", sender_name: str = "",
                 receiver_rnc: str = "", encf: str = "", ecf_type: str = "",
                 xml_content: str = "", status: str = "recibido",
                 received_at: Optional[str] = None, **kwargs):
        self.id = id
        self.sender_rnc = sender_rnc
        self.sender_name = sender_name
        self.receiver_rnc = receiver_rnc
        self.encf = encf
        self.ecf_type = ecf_type
        self.xml_content = xml_content
        self.status = status
        self.received_at = received_at or datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return {
            "sender_rnc": self.sender_rnc,
            "sender_name": self.sender_name,
            "receiver_rnc": self.receiver_rnc,
            "encf": self.encf,
            "ecf_type": self.ecf_type,
            "xml_content": self.xml_content,
            "status": self.status,
            "received_at": self.received_at,
        }

    @staticmethod
    def from_dict(id: str, data: dict):
        return ReceivedApproval(id=id, **data)
