from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class ImageProcessingResult:
    raw_path: Path
    warped_path: Path
    face_raw_path: Path
    face_enhanced_path: Path
    document_corners: list[list[float]] | None = None
    face_box: list[int] | None = None
    restoration_method: str = "opencv_enhancement"
    warnings: list[str] = field(default_factory=list)


def decode_upload(file_bytes: bytes) -> np.ndarray:
    data = np.frombuffer(file_bytes, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("El archivo no es una imagen válida.")
    return image


def save_image(path: Path, image: np.ndarray) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), image)
    if not ok:
        raise IOError(f"No se pudo escribir la imagen en {path}")
    return path


def order_points(points: np.ndarray) -> np.ndarray:
    rect = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1)
    rect[0] = points[np.argmin(sums)]
    rect[2] = points[np.argmax(sums)]
    rect[1] = points[np.argmin(diffs)]
    rect[3] = points[np.argmax(diffs)]
    return rect


def four_point_transform(image: np.ndarray, points: np.ndarray) -> np.ndarray:
    rect = order_points(points.astype("float32"))
    top_left, top_right, bottom_right, bottom_left = rect

    width_a = np.linalg.norm(bottom_right - bottom_left)
    width_b = np.linalg.norm(top_right - top_left)
    max_width = max(1, int(max(width_a, width_b)))

    height_a = np.linalg.norm(top_right - bottom_right)
    height_b = np.linalg.norm(top_left - bottom_left)
    max_height = max(1, int(max(height_a, height_b)))

    destination = np.array(
        [[0, 0], [max_width - 1, 0], [max_width - 1, max_height - 1], [0, max_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(rect, destination)
    return cv2.warpPerspective(image, matrix, (max_width, max_height))


def resize_for_detection(image: np.ndarray, max_side: int = 1200) -> tuple[np.ndarray, float]:
    height, width = image.shape[:2]
    largest = max(height, width)
    if largest <= max_side:
        return image.copy(), 1.0
    scale = max_side / largest
    resized = cv2.resize(image, (round(width * scale), round(height * scale)), interpolation=cv2.INTER_AREA)
    return resized, scale


def detect_document_corners(image: np.ndarray) -> np.ndarray | None:
    resized, scale = resize_for_detection(image)
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 9, 75, 75)
    edges = cv2.Canny(gray, 35, 130)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    image_area = resized.shape[0] * resized.shape[1]
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:12]:
        area = cv2.contourArea(contour)
        if area < image_area * 0.08:
            continue
        perimeter = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.02 * perimeter, True)
        if len(approx) == 4:
            return approx.reshape(4, 2).astype("float32") / scale

    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < image_area * 0.08:
        return None
    rect = cv2.minAreaRect(largest)
    box = cv2.boxPoints(rect)
    return box.astype("float32") / scale


def correct_perspective(image: np.ndarray) -> tuple[np.ndarray, np.ndarray | None, list[str]]:
    warnings: list[str] = []
    corners = detect_document_corners(image)
    if corners is None:
        warnings.append("No se detectaron cuatro bordes claros; se usó la imagen original.")
        normalized, rotated = normalize_landscape_document(image)
        if rotated:
            warnings.append("La identificacion estaba vertical; se ajusto a modo horizontal.")
        return normalized, None, warnings

    warped = four_point_transform(image, corners)
    h, w = warped.shape[:2]
    if min(h, w) < 200:
        warnings.append("La corrección de perspectiva produjo un recorte muy pequeño; se usó la imagen original.")
        normalized, rotated = normalize_landscape_document(image)
        if rotated:
            warnings.append("La identificacion estaba vertical; se ajusto a modo horizontal.")
        return normalized, None, warnings
    warped, rotated = normalize_landscape_document(warped)
    if rotated:
        warnings.append("La identificacion estaba vertical; se ajusto a modo horizontal.")
    return warped, corners, warnings


def normalize_landscape_document(image: np.ndarray) -> tuple[np.ndarray, bool]:
    h, w = image.shape[:2]
    if w >= h:
        return image, False

    candidates = [
        cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE),
        cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
    ]

    def score_candidate(candidate: np.ndarray) -> float:
        face_box = detect_face_bbox(candidate)
        if face_box is None:
            return 0.0
        x, _, bw, bh = face_box
        center_x = (x + bw / 2) / max(1, candidate.shape[1])
        score = float(bw * bh)
        if center_x < 0.48:
            score *= 1.35
        return score

    scored = [(score_candidate(candidate), candidate) for candidate in candidates]
    best_score, best_candidate = max(scored, key=lambda item: item[0])
    if best_score > 0:
        return best_candidate, True
    return candidates[0], True


def detect_face_bbox(image: np.ndarray) -> tuple[int, int, int, int] | None:
    mp_box = _detect_face_with_mediapipe(image)
    if mp_box:
        return mp_box
    return _detect_face_with_haar(image)


def _detect_face_with_mediapipe(image: np.ndarray) -> tuple[int, int, int, int] | None:
    try:
        import mediapipe as mp
    except Exception:
        return None

    rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    with mp.solutions.face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.45) as detector:
        results = detector.process(rgb)
    if not results.detections:
        return None

    h, w = image.shape[:2]
    boxes = []
    for detection in results.detections:
        relative = detection.location_data.relative_bounding_box
        x = max(0, int(relative.xmin * w))
        y = max(0, int(relative.ymin * h))
        bw = min(w - x, int(relative.width * w))
        bh = min(h - y, int(relative.height * h))
        if bw > 0 and bh > 0:
            score = detection.score[0] if detection.score else 0
            boxes.append((score, x, y, bw, bh))
    if not boxes:
        return None
    _, x, y, bw, bh = max(boxes, key=lambda item: item[0] * item[3] * item[4])
    return x, y, bw, bh


def _detect_face_with_haar(image: np.ndarray) -> tuple[int, int, int, int] | None:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    detector = cv2.CascadeClassifier(cascade_path)
    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.08,
        minNeighbors=4,
        minSize=(40, 40),
        flags=cv2.CASCADE_SCALE_IMAGE,
    )
    if len(faces) == 0:
        return None
    x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
    return int(x), int(y), int(w), int(h)


def crop_portrait(image: np.ndarray, face_box: tuple[int, int, int, int] | None) -> np.ndarray:
    h, w = image.shape[:2]
    if face_box is None:
        side_w = int(w * 0.42)
        side_h = int(h * 0.72)
        cx, cy = w // 2, h // 2
        return crop_with_padding(image, cx - side_w // 2, cy - side_h // 2, cx + side_w // 2, cy + side_h // 2)

    x, y, bw, bh = face_box
    cx = x + bw / 2
    portrait_w = bw * 1.48
    portrait_h = portrait_w / 0.72
    top = y - bh * 0.55
    bottom = top + portrait_h
    left = cx - portrait_w / 2
    right = cx + portrait_w / 2
    return crop_with_padding(image, left, top, right, bottom)


def crop_with_padding(
    image: np.ndarray,
    left: float,
    top: float,
    right: float,
    bottom: float,
    color: tuple[int, int, int] = (255, 255, 255),
) -> np.ndarray:
    h, w = image.shape[:2]
    left_i, top_i, right_i, bottom_i = map(lambda v: int(round(v)), (left, top, right, bottom))
    pad_left = max(0, -left_i)
    pad_top = max(0, -top_i)
    pad_right = max(0, right_i - w)
    pad_bottom = max(0, bottom_i - h)
    if any((pad_left, pad_top, pad_right, pad_bottom)):
        image = cv2.copyMakeBorder(image, pad_top, pad_bottom, pad_left, pad_right, cv2.BORDER_CONSTANT, value=color)
        left_i += pad_left
        right_i += pad_left
        top_i += pad_top
        bottom_i += pad_top
    return image[max(0, top_i) : max(0, bottom_i), max(0, left_i) : max(0, right_i)]


def restore_face(face: np.ndarray) -> tuple[np.ndarray, str, list[str]]:
    warnings: list[str] = []

    if os.getenv("ENABLE_FACE_RESTORATION", "0") == "1":
        restored = _restore_with_gfpgan(face, warnings)
        if restored is not None:
            return restored, "gfpgan_local", warnings

        restored = _restore_with_opencv_superres(face, warnings)
        if restored is not None:
            return restored, "opencv_dnn_superres", warnings

    if os.getenv("ENABLE_FACE_LIGHT_FIX", "0") == "1":
        return _light_balance_only(face), "light_balance_only", warnings

    return face.copy(), "original_crop", warnings


def _restore_with_gfpgan(face: np.ndarray, warnings: list[str]) -> np.ndarray | None:
    model_path = os.getenv("GFPGAN_MODEL_PATH")
    if not model_path:
        return None
    try:
        from gfpgan import GFPGANer

        restorer = GFPGANer(
            model_path=model_path,
            upscale=int(os.getenv("GFPGAN_UPSCALE", "2")),
            arch=os.getenv("GFPGAN_ARCH", "clean"),
            channel_multiplier=int(os.getenv("GFPGAN_CHANNEL_MULTIPLIER", "2")),
            bg_upsampler=None,
        )
        _, _, restored = restorer.enhance(
            face,
            has_aligned=False,
            only_center_face=False,
            paste_back=True,
        )
        return restored
    except Exception as exc:
        warnings.append(f"GFPGAN local falló: {exc}")
        return None


def _restore_with_opencv_superres(face: np.ndarray, warnings: list[str]) -> np.ndarray | None:
    model_path = os.getenv("OPENCV_SR_MODEL_PATH")
    if not model_path:
        return None
    try:
        sr = cv2.dnn_superres.DnnSuperResImpl_create()
        sr.readModel(model_path)
        sr.setModel(os.getenv("OPENCV_SR_ALGORITHM", "edsr"), int(os.getenv("OPENCV_SR_SCALE", "2")))
        return sr.upsample(face)
    except Exception as exc:
        warnings.append(f"Super-resolución OpenCV falló: {exc}")
        return None


def _enhance_face_cv(face: np.ndarray) -> np.ndarray:
    h, w = face.shape[:2]
    scale = 2 if max(h, w) < 900 else 1
    enhanced = cv2.resize(face, (w * scale, h * scale), interpolation=cv2.INTER_CUBIC)
    enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 4, 4, 7, 21)

    lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    enhanced = cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)

    blur = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.2)
    enhanced = cv2.addWeighted(enhanced, 1.32, blur, -0.32, 0)
    return enhanced


def _light_balance_only(face: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(face, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=1.35, tileGridSize=(8, 8))
    l_channel = clahe.apply(l_channel)
    return cv2.cvtColor(cv2.merge((l_channel, a_channel, b_channel)), cv2.COLOR_LAB2BGR)


def process_identification(file_bytes: bytes, session_dir: Path) -> ImageProcessingResult:
    session_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    raw = decode_upload(file_bytes)
    raw_path = save_image(session_dir / "raw.jpg", raw)

    warped, corners, perspective_warnings = correct_perspective(raw)
    warnings.extend(perspective_warnings)
    warped_path = save_image(session_dir / "warped.jpg", warped)

    face_box = detect_face_bbox(warped)
    if face_box is None:
        warnings.append("No se detectó rostro con suficiente confianza; se usó un recorte central.")
    portrait = crop_portrait(warped, face_box)
    face_raw_path = save_image(session_dir / "face_raw.jpg", portrait)

    enhanced, method, restoration_warnings = restore_face(portrait)
    warnings.extend(restoration_warnings)
    face_enhanced_path = save_image(session_dir / "face_enhanced.jpg", enhanced)

    return ImageProcessingResult(
        raw_path=raw_path,
        warped_path=warped_path,
        face_raw_path=face_raw_path,
        face_enhanced_path=face_enhanced_path,
        document_corners=corners.tolist() if corners is not None else None,
        face_box=list(face_box) if face_box is not None else None,
        restoration_method=method,
        warnings=warnings,
    )
