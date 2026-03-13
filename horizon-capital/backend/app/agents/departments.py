"""Department type enumeration for Horizon Capital's organizational structure."""

from enum import Enum


class DepartmentType(str, Enum):
    FRONT_OFFICE = "front_office"       # Investment & Revenue
    MIDDLE_OFFICE = "middle_office"     # Risk & Control
    BACK_OFFICE = "back_office"         # Support & Finance
    EXECUTIVE = "executive"             # Executive Management
