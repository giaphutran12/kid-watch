"""
KID-WATCH v0.1 — Phone Detector
YOLOv8-based cell phone detection
"""

from ultralytics import YOLO

from ..config import PHONE_CONFIDENCE_THRESHOLD


class PhoneDetector:
    """Detects cell phone using YOLOv8."""

    # COCO class ID for cell phone
    PHONE_CLASS_ID = 67
    # Aspect ratio thresholds (phones are ~0.4-2.5; pens are < 0.3 or > 3.0)
    PHONE_ASPECT_RATIO_MIN = 0.35
    PHONE_ASPECT_RATIO_MAX = 2.8
    # Minimum bounding box area (phones are at least ~60x80 pixels at 720p)
    PHONE_MIN_BOX_AREA = 4000
    # Epsilon for numerical stability in division
    EPSILON = 1e-6

    def __init__(self):
        print("Loading YOLOv8n model (first run will download ~6MB)...")
        self.model = YOLO("yolov8n.pt")

    def detect(self, frame):
        """
        Returns: (phone_detected, bounding_boxes)
        """
        results = self.model(frame, verbose=False, conf=PHONE_CONFIDENCE_THRESHOLD)

        phone_boxes = []
        for result in results:
            boxes = result.boxes
            for box in boxes:
                class_id = int(box.cls[0])
                confidence = float(box.conf[0])

                if class_id == self.PHONE_CLASS_ID:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()

                    # === Filter false positives (pens, pencils, thin objects) ===
                    box_width = x2 - x1
                    box_height = y2 - y1
                    aspect_ratio = box_width / (box_height + self.EPSILON)
                    box_area = box_width * box_height

                    # Phones have aspect ratio 0.4-2.5; pens are < 0.3 or > 3.0
                    if (
                        aspect_ratio < self.PHONE_ASPECT_RATIO_MIN
                        or aspect_ratio > self.PHONE_ASPECT_RATIO_MAX
                    ):
                        continue  # Too elongated — likely a pen/pencil/stylus

                    # Phones are at least ~60x80 pixels at 720p
                    if box_area < self.PHONE_MIN_BOX_AREA:
                        continue  # Too small to be a phone
                    # === END filter ===

                    phone_boxes.append(
                        {
                            "bbox": (int(x1), int(y1), int(x2), int(y2)),
                            "confidence": confidence,
                        }
                    )

        return len(phone_boxes) > 0, phone_boxes
