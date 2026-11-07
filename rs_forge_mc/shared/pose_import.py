# SPDX-License-Identifier: GPL-3.0-only
"""Explicit JSON adapters into reusable MHR poses. No file writes or inference.

2D keypoints are embedded in the frontal XY plane, never presented as recovered
3D depth. Foreign local rotations require their own skeleton and bind frames.
"""
import copy
import hashlib
import io
import json
import re
import warnings as python_warnings
import zipfile

import numpy as np

from . import mhr
from .pose_library import MAX_CATALOGUE_BYTES, _entry, retarget_points

MAX_IMPORT_POSES = 2000
POSITION_MAPPING = dict(pelvis=1, chest=5, neck=6, head=7,
                        left_shoulder=12, left_elbow=13, left_wrist=14,
                        right_shoulder=34, right_elbow=35, right_wrist=36,
                        left_hip=55, left_knee=56, left_ankle=58,
                        right_hip=66, right_knee=67, right_ankle=69)
COCO_MAPPING = dict(neck=1, right_shoulder=2, right_elbow=3, right_wrist=4,
                    left_shoulder=5, left_elbow=6, left_wrist=7,
                    right_hip=8, right_knee=9, right_ankle=10,
                    left_hip=11, left_knee=12, left_ankle=13)
BODY25_MAPPING = dict(COCO_MAPPING, right_hip=9, right_knee=10, right_ankle=11,
                      left_hip=12, left_knee=13, left_ankle=14)


def _direction_notice():
    return ('Body directions retargeted to MHR proportions; finger articulation and axial twist are not preserved. '
            '/ 신체 방향을 MHR 체형으로 변환합니다. 손가락 회전과 축 비틀림은 보존되지 않습니다.')


def _editor_scene(raw):
    """FK for the verified Yu Zhu editor hierarchy (not arbitrary Three scenes)."""
    from .pose3d import rotation
    content = raw.get('object')
    bodies = content.get('bodies') if isinstance(content, dict) else None
    if not isinstance(bodies, list) or not 1 <= len(bodies) <= 10:
        raise ValueError('Open Pose Editor scene needs 1–10 bodies.')
    hierarchy = {'torso': (None, [0, 115, 0]), 'five': ('torso', [0, 23, 0]),
                 'neck': ('five', [0, 0, 0]), 'nose': ('neck', [0, 20, 14])}
    for side, sign in [('left', 1), ('right', -1)]:
        for joint, parent, pos in [
            ('shoulder_inner', 'five', [0, 0, 0]), ('shoulder', side+'_shoulder_inner', [17*sign, 0, 0]),
            ('elbow', side+'_shoulder', [0, -25, 0]), ('wrist', side+'_elbow', [0, -25, 0]),
            ('hip_inner', 'five', [0, 0, 0]), ('hip', side+'_hip_inner', [10*sign, -46, 0]),
            ('knee', side+'_hip', [0, -40, 0]), ('ankle', side+'_knee', [0, -36, 0])]:
            hierarchy[side+'_'+joint] = (parent, pos)
    for body in bodies:
        if not isinstance(body, dict) or not isinstance(body.get('child'), dict):
            raise ValueError('Invalid Open Pose Editor body.')
        children = body['child']
        required = {k for k in hierarchy if k != 'torso'}
        if not required <= children.keys():
            raise ValueError('Unrecognized Open Pose Editor hierarchy; required body nodes are missing. / 외부 편집기의 뼈대 구조가 다릅니다.')
        matrices = {}
        for name, (parent, offset) in hierarchy.items():
            source = body if parent is None else children[name]
            if not isinstance(source, dict):
                raise ValueError('Invalid body transform.')
            position = _array(source.get('position', offset), (3,), name)
            scale = _array(source.get('scale', [1, 1, 1]), (3,), name)
            raw_rotation = source.get('rotation', [0, 0, 0, 'XYZ'])
            if not isinstance(raw_rotation, list) or len(raw_rotation) not in (3, 4) or (len(raw_rotation) == 4 and raw_rotation[3] != 'XYZ'):
                raise ValueError('Open Pose Editor rotation must use XYZ Euler radians.')
            angles = _array(raw_rotation[:3], (3,), name)
            matrix = np.eye(4)
            matrix[:3, :3] = rotation(np.rad2deg(angles)) @ np.diag(scale)
            matrix[:3, 3] = position
            matrices[name] = matrices[parent] @ matrix if parent else matrix
        points = {k: v[:3, 3] for k, v in matrices.items()}
        points['pelvis'] = (points['left_hip'] + points['right_hip']) / 2
        points['chest'] = points['pelvis'] * .35 + points['neck'] * .65
        points['head'] = points['nose']
        yield retarget_points(points)


def import_bvh(text, filename, *, frame=0):
    """Parse a bounded BVH hierarchy and sample one explicit zero-based frame.

    FK honors each joint's declared channel order, including root translation.
    Named anatomical landmarks allow CMU/Mixamo-style rigs without assuming
    their joint indices or applying foreign local angles to native MHR bones.
    """
    if type(frame) is not int or frame < 0:
        raise ValueError('BVH frame must be a nonnegative integer. / BVH 프레임은 0 이상 정수입니다.')
    try:
        hierarchy, motion = re.split(r'\bMOTION\b', text, maxsplit=1)
        tokens = re.findall(r'[{}]|[^\s{}]+', hierarchy)
        if len(tokens) > 10000:
            raise ValueError('BVH hierarchy is too large.')
        cursor, nodes, channel_count = 0, [], 0

        def take(expected=None):
            nonlocal cursor
            if cursor >= len(tokens):
                raise ValueError('Truncated BVH hierarchy.')
            token = tokens[cursor]
            cursor += 1
            if expected is not None and token != expected:
                raise ValueError(f'BVH expected {expected}.')
            return token

        def node(parent, depth=0):
            nonlocal channel_count
            if depth > 64 or len(nodes) >= 256:
                raise ValueError('BVH skeleton exceeds 256 nodes / depth 64.')
            kind = take()
            if kind not in ('ROOT', 'JOINT', 'End') or ((parent is None) != (kind == 'ROOT')):
                raise ValueError('Invalid BVH joint type.')
            name = take('Site') if kind == 'End' else take()
            take('{'); take('OFFSET')
            offset = _array([float(take()) for _ in range(3)], (3,), 'BVH offset')
            channels = []
            if kind != 'End':
                take('CHANNELS')
                count = int(take())
                if not 0 <= count <= 6:
                    raise ValueError('Invalid BVH channel count.')
                channels = [take() for _ in range(count)]
                if len(set(channels)) != count or any(c not in {a+b for a in 'XYZ' for b in ('position', 'rotation')} for c in channels):
                    raise ValueError('Invalid/duplicate BVH channels.')
            index = len(nodes)
            nodes.append(dict(name=name, parent=parent, offset=offset, channels=channels, start=channel_count))
            channel_count += len(channels)
            while cursor < len(tokens) and tokens[cursor] != '}':
                if kind == 'End':
                    raise ValueError('BVH End Site cannot have children.')
                node(index, depth+1)
            take('}')

        take('HIERARCHY'); node(None)
        if cursor != len(tokens) or channel_count == 0:
            raise ValueError('Invalid BVH hierarchy.')
        match = re.match(r'\s*Frames\s*:\s*(\d+)\s+Frame\s+Time\s*:\s*([^\s]+)\s+', motion)
        if not match:
            raise ValueError('BVH motion header is missing.')
        frames, timestep = int(match[1]), float(match[2])
        if not 1 <= frames <= 200000 or not np.isfinite(timestep) or timestep <= 0 or frame >= frames:
            raise ValueError(f'BVH frame outside motion range (0–{frames-1}) or invalid frame time. / BVH 프레임 범위를 확인하세요.')
        values_text = motion[match.end():]
        if re.search(r'[^0-9eE+.\-\s]', values_text):
            raise ValueError('Invalid BVH motion values.')
        with python_warnings.catch_warnings():
            python_warnings.simplefilter('error', DeprecationWarning)
            values = np.fromstring(values_text, sep=' ')
        if len(values) != frames*channel_count or not np.isfinite(values).all() or (np.abs(values) > 1e8).any():
            raise ValueError('BVH frame/channel counts or numeric values are invalid.')
        sample = values.reshape(frames, channel_count)[frame]
        matrices, positions = [], {}
        for bone in nodes:
            r, t = np.eye(3), bone['offset'].copy()
            for name, value in zip(bone['channels'], sample[bone['start']:]):
                axis = 'XYZ'.index(name[0])
                if name.endswith('position'):
                    t += r[:, axis] * value
                else:
                    angles = [0., 0., 0.]; angles[axis] = value
                    r = r @ mhr.rotation(angles)
            matrix = np.eye(4); matrix[:3, :3] = r; matrix[:3, 3] = t
            if bone['parent'] is not None:
                matrix = matrices[bone['parent']] @ matrix
            matrices.append(matrix)
            if bone['name'] != 'Site':
                key = re.sub(r'[^a-z0-9]', '', bone['name'].rsplit(':', 1)[-1].lower())
                if key in positions:
                    raise ValueError('Ambiguous duplicate BVH joint names.')
                positions[key] = matrix[:3, 3]
        aliases = dict(pelvis=['hips', 'hip', 'pelvis', 'root'],
                       chest=['spine2', 'chest', 'upperchest', 'spine1', 'spine', 'lowerback'],
                       neck=['neck', 'neck1', 'lowerneck', 'upperneck'], head=['head'])
        for side, short in [('left', 'l'), ('right', 'r')]:
            aliases.update({side+'_'+k: [side+a for a in full]+[short+a for a in short_names]
                            for k, full, short_names in [
                                ('shoulder', ['arm', 'upperarm', 'shoulder'], ['humerus', 'upperarm', 'shoulder', 'shldr']),
                                ('elbow', ['forearm', 'lowerarm', 'elbow'], ['radius', 'forearm', 'elbow']),
                                ('wrist', ['hand', 'wrist'], ['hand', 'wrist']),
                                ('hip', ['upleg', 'thigh', 'upperleg', 'hip'], ['femur', 'thigh', 'upleg', 'hipjoint']),
                                ('knee', ['leg', 'lowerleg', 'shin', 'knee'], ['tibia', 'shin', 'leg', 'knee']),
                                ('ankle', ['foot', 'ankle'], ['foot', 'ankle'])]})
        targets = {k: positions[next(n for n in names if n in positions)] for k, names in aliases.items() if any(n in positions for n in names)}
        missing = set(aliases) - targets.keys()
        if missing:
            raise ValueError('BVH bone names not recognized: '+', '.join(sorted(missing))+
                             '. / BVH 관절 이름을 인식하지 못했습니다. CMU/Mixamo 계열의 표준 이름이 필요합니다.')
        pose = _pose(f'{_name(filename)} / frame {frame}', retarget_points(targets))
        return dict(format='bvh', poses=[pose], warnings=[_direction_notice(),
                    f'Imported frame {frame} of {frames} (0-based), Y-up. Motion, root travel and body proportions are excluded. / 전체 {frames}프레임 중 {frame}번(Y-up) 자세만 가져옵니다. 애니메이션·루트 이동·원래 체형은 제외됩니다.'], rejected=[])
    except (IndexError, TypeError, OverflowError, DeprecationWarning) as error:
        raise ValueError('Invalid BVH file. / BVH 파일 구조나 수치를 확인하세요.') from error


def import_file(raw, filename, *, frame=0):
    """User-selected JSON/BVH/ZIP bytes; ZIPs are read in memory, never extracted."""
    if not isinstance(raw, bytes) or len(raw) > MAX_CATALOGUE_BYTES:
        raise ValueError('Pose file must be under 32 MB. / 포즈 파일은 32 MB 이하여야 합니다.')
    extension = filename.rsplit('.', 1)[-1].lower()
    if extension == 'zip' or raw.startswith(b'PK\x03\x04'):
        poses, notes, rejected = [], [], []
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                files = archive.infolist()
                candidates = [f for f in files if not f.is_dir() and f.filename.rsplit('.', 1)[-1].lower() in ('json', 'bvh') and '__MACOSX/' not in f.filename]
                if not 1 <= len(candidates) <= 2000 or len(files) > 5000 or sum(f.file_size for f in candidates) > MAX_CATALOGUE_BYTES:
                    raise ValueError('ZIP needs 1–2000 JSON/BVH files, 32 MB total uncompressed. / ZIP 내부 JSON/BVH는 1~2000개·압축 해제 기준 합계 32 MB 이하여야 합니다.')
                for item in candidates:
                    try:
                        payload = archive.read(item)
                        if payload.startswith(b'PK\x03\x04'):
                            raise ValueError('Nested archives are not imported. / 중첩 ZIP은 가져오지 않습니다.')
                        result = import_file(payload, item.filename, frame=frame)
                        if len(poses)+len(result['poses']) > MAX_IMPORT_POSES:
                            raise ValueError('ZIP exceeds 2000 poses; split the archive. / ZIP의 포즈를 2000개 이하로 나누세요.')
                        poses.extend(result['poses'])
                        notes.extend(result['warnings'])
                        rejected.extend(dict(file=item.filename, **r) for r in result['rejected'])
                    except (ValueError, RuntimeError, OSError) as error:
                        rejected.append(dict(file=item.filename, reason=str(error)))
            if not poses:
                raise ValueError('No usable poses in ZIP. / ZIP에서 읽을 수 있는 포즈가 없습니다. '+rejected[0]['reason'])
            if rejected:
                notes.append(f'{len(rejected)} invalid files/poses skipped. / 잘못된 파일·포즈 {len(rejected)}개를 제외했습니다.')
            return dict(format='zip', poses=poses, warnings=list(dict.fromkeys(notes))[:100], rejected=rejected[:2000])
        except (zipfile.BadZipFile, zipfile.LargeZipFile, NotImplementedError) as error:
            raise ValueError('Invalid or unsupported ZIP archive. / ZIP 파일을 확인하세요.') from error
    if extension == 'bvh' or raw.lstrip().startswith(b'HIERARCHY'):
        try:
            return import_bvh(raw.decode('utf-8-sig'), filename, frame=frame)
        except UnicodeError as error:
            raise ValueError('Use a UTF-8 BVH file.') from error
    return import_poses(raw, filename)


def _array(raw, shape, label):
    # Reject numeric strings and booleans rather than silently coercing them.
    try:
        array = np.asarray(raw)
        if array.shape != shape or array.dtype.kind not in 'iuf':
            raise ValueError()
        array = array.astype(float)
        if not np.isfinite(array).all() or (np.abs(array) > 1e8).any():
            raise ValueError()
        return array
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f'{label}: invalid coordinates. / 좌표 형식이나 수치를 확인하세요.') from error


def _name(filename):
    name = str(filename).replace('\\', '/').rsplit('/', 1)[-1]
    return (name.rsplit('.', 1)[0].strip() or 'Imported pose')[:130]


def _pose(name, pose):
    payload = json.dumps(pose, sort_keys=True, allow_nan=False)
    identity = 'import-' + hashlib.sha256((name + payload).encode()).hexdigest()[:24]
    return _entry(dict(id=identity, name=name, **pose), set())


def _openpose_person(person, meta):
    if not isinstance(person, dict):
        raise ValueError('Invalid person entry. / 인물 데이터가 잘못됐습니다.')
    raw = person.get('pose_keypoints_2d')
    if not isinstance(raw, list) or len(raw) not in (54, 75):
        raise ValueError('Use COCO-18 or BODY-25 pose_keypoints_2d. / COCO-18·BODY-25 신체 좌표가 필요합니다.')
    count = len(raw) // 3
    points = _array(raw, (len(raw),), 'OpenPose').reshape(count, 3)
    if (points[:, 2] < 0).any() or (points[:, 2] > 1).any():
        raise ValueError('OpenPose confidence must be 0–1. / 관절 신뢰도는 0~1이어야 합니다.')
    layout = 'COCO_18' if count == 18 else 'BODY_25'
    if meta.get('pose_model', layout) != layout:
        raise ValueError('Declared pose_model differs from keypoint count. / 관절 수와 pose_model이 다릅니다.')
    notes = []
    valid = points[points[:, 2] >= .2, :2]
    space = meta.get('coordinate_space', 'pixels')
    if 'coordinate_space' not in meta and valid.size and np.max(np.abs(valid)) <= 2:
        if 'canvas_width' not in meta or 'canvas_height' not in meta:
            raise ValueError('Ambiguous normalized coordinates. Declare coordinate_space and canvas_width/height. / 정규화 좌표에는 원본 canvas_width/height가 필요합니다.')
        space = 'normalized_signed' if np.min(valid) < 0 else 'normalized'
        notes.append(f'Inferred {space} coordinates using source canvas dimensions. / 좌표 범위와 원본 캔버스 크기로 정규화 좌표({space})를 판별했습니다.')
    if space not in ('pixels', 'normalized', 'normalized_signed'):
        raise ValueError('Use pixels, normalized [0,1] or normalized_signed [-1,1] coordinates. / 좌표 단위는 pixels·normalized·normalized_signed를 사용하세요.')
    if space in ('normalized', 'normalized_signed'):
        width, height = meta.get('canvas_width'), meta.get('canvas_height')
        if any(type(v) not in (int, float) or not np.isfinite(v) or not 1 <= v <= 100000 for v in (width, height)):
            raise ValueError('Normalized coordinates need canvas_width/height. / 정규화 좌표에는 원본 캔버스 크기가 필요합니다.')
        low = -1 if space == 'normalized_signed' else 0
        if (valid < low).any() or (valid > 1).any():
            raise ValueError(f'Normalized coordinates must be in [{low}, 1]. / 정규화 좌표 범위를 확인하세요.')
        if space == 'normalized_signed':
            points[:, :2] = (points[:, :2]+1)/2
        points[:, :2] *= [width, height]
    # OpenPose image Y points down; MHR world Y points up. Depth is zero.
    mapping = COCO_MAPPING if count == 18 else BODY25_MAPPING
    positions = {k: np.array([points[i, 0], -points[i, 1], 0.])
                 for k, i in mapping.items() if points[i, 2] >= .2}
    required = {'left_shoulder', 'right_shoulder', 'left_hip', 'right_hip'}
    if not required <= positions.keys():
        raise ValueError('Both shoulders and hips need confidence ≥0.2; use a full-body pose. / 양쪽 어깨·골반 좌표(신뢰도 0.2 이상)가 필요합니다.')
    if 'neck' not in positions:
        positions['neck'] = (positions['left_shoulder'] + positions['right_shoulder']) / 2
        notes.append('Missing neck: used shoulder midpoint. / 목 좌표가 없어 양 어깨 중점을 사용했습니다.')
    positions['pelvis'] = (positions['left_hip'] + positions['right_hip']) / 2
    positions['chest'] = positions['pelvis'] * .35 + positions['neck'] * .65
    torso = np.linalg.norm(positions['neck'] - positions['pelvis'])
    if torso < 1e-6:
        raise ValueError('Collapsed torso. / 몸통 길이가 너무 짧습니다.')
    if points[0, 2] >= .2:
        head = np.array([points[0, 0], -points[0, 1], 0.])
        if np.linalg.norm(head - positions['neck']) > torso * .01:
            positions['head'] = head
    missing = []
    for side in ('left', 'right'):
        for a, b in [('shoulder', 'elbow'), ('elbow', 'wrist'), ('hip', 'knee'), ('knee', 'ankle')]:
            a, b = side + '_' + a, side + '_' + b
            if a in positions and b in positions:
                if not .01 <= np.linalg.norm(positions[b] - positions[a]) / torso <= 5:
                    # A foreshortened/collapsed 2D segment has no reliable aim.
                    positions.pop(b)
            if a not in positions or b not in positions:
                missing.append(a)
    if missing:
        notes.append('Missing/low-confidence or collapsed segments keep default local rotations: '
                     + ', '.join(missing) + '. / 누락·저신뢰도·겹친 관절 구간은 기본 회전을 유지합니다.')
    if any(person.get(k) for k in ('hand_left_keypoints_2d', 'hand_right_keypoints_2d',
                                  'hand_left_keypoints_3d', 'hand_right_keypoints_3d', 'face_keypoints_2d', 'face_keypoints_3d')):
        notes.append('Hand/face landmarks are not imported; adjust fingers afterward. / 손·얼굴 좌표는 가져오지 않습니다. 손가락은 편집기에서 조절하세요.')
    return retarget_points(positions, partial=True), notes


def import_poses(raw, filename='Imported pose.json'):
    """Return validated poses plus visible conversion limitations, without writes."""
    if isinstance(raw, (str, bytes)):
        if len(raw.encode('utf-8') if isinstance(raw, str) else raw) > MAX_CATALOGUE_BYTES:
            raise ValueError('Pose file exceeds 32 MB. / 포즈 파일은 32 MB 이하여야 합니다.')
        try:
            raw = json.loads(raw.decode('utf-8-sig') if isinstance(raw, bytes) else raw.lstrip('\ufeff'))
        except (ValueError, UnicodeError, RecursionError) as error:
            raise ValueError('Invalid UTF-8 JSON pose file. / UTF-8 JSON 포즈 파일을 확인하세요.') from error
    title, poses, warnings, rejected = _name(filename), [], [], []
    if isinstance(raw, dict) and raw.get('schema') == 'rs.pose-library.v1':
        source = raw.get('poses')
        if not isinstance(source, list) or not 1 <= len(source) <= MAX_IMPORT_POSES:
            raise ValueError('RS library needs 1–2000 poses. / RS 라이브러리는 1~2000개씩 가져오세요.')
        used = set()
        for item in source:
            entry = _entry(item, used)
            poses.append(_pose(entry['name'], dict(joints=entry['joints'], floor_y=entry['floor_y'])))
            used.add(entry['id'])
        kind = 'rs.pose-library.v1'
    elif isinstance(raw, dict) and raw.get('header') == 'Openpose Editor by Yu Zhu':
        poses = [_pose(f'{title} / {i+1}', pose) for i, pose in enumerate(_editor_scene(raw))]
        kind = 'open-pose-editor.scene'
        warnings.extend([_direction_notice(), 'Source camera and placement are excluded. / 원본 카메라·인물 배치는 가져오지 않습니다.'])
    elif isinstance(raw, dict) and type(raw.get('version')) is int and raw['version'] in (1, 2) and 'camera' in raw:
        from .pose3d import read_scene, skeleton
        scene = read_scene(raw)
        for p in scene['people']:
            if scene['version'] == 2:
                pose = dict(joints=copy.deepcopy(p['joints']))
            else:
                local = dict(p, position=[0, 0, 0], rotation=[0, 0, 0], scale=1., bulk=1.)
                pose = retarget_points(skeleton(local)[0])
            poses.append(_pose(f'{title} / {p["id"]}', pose))
        kind = f'rs.scene.v{scene["version"]}'
        warnings.append('Imported reusable poses only; scene camera, placement and crop are excluded. Use Load scene to restore the complete RS scene. / 자세만 가져왔습니다. 카메라·배치·크롭 복원은 장면 불러오기를 사용하세요.')
        if scene['version'] == 1:
            warnings.append('Legacy RS body directions retargeted; axial twist is not preserved. / 구형 RS 자세는 뼈 방향을 변환하며 축 비틀림은 보존되지 않습니다.')
    else:
        # comfyui_controlnet_aux can export a list of frames. Keep each frame
        # and person explicitly named; this imports static poses, not motion.
        if isinstance(raw, list) and raw and isinstance(raw[0], dict) and 'people' in raw[0]:
            if len(raw) > MAX_IMPORT_POSES:
                raise ValueError('Import up to 2000 OpenPose frames at a time.')
            kind = 'openpose.frames.2d'
            for frame_index, frame in enumerate(raw):
                try:
                    result = import_poses(frame, f'{title} / frame {frame_index}.json')
                    if len(poses)+len(result['poses']) > MAX_IMPORT_POSES:
                        raise ValueError('More than 2000 poses; split the frame collection.')
                    poses.extend(result['poses'])
                    warnings.extend(result['warnings'])
                    rejected.extend(dict(frame=frame_index, **r) for r in result['rejected'])
                except ValueError as error:
                    rejected.append(dict(frame=frame_index, reason=str(error)))
        elif isinstance(raw, dict) and isinstance(raw.get('people'), list):
            source = raw['people']
            if not 1 <= len(source) <= 10:
                raise ValueError('OpenPose frame needs 1–10 people. / OpenPose 한 프레임은 1~10명이어야 합니다.')
            kind = 'openpose.2d'
            warnings.append('2D → frontal planar 3D approximation (depth=0); perspective, axial twist and original body proportions are not recovered. / 2D 좌표를 깊이 0의 정면 3D 자세로 근사합니다. 원근·축 비틀림·원래 체형은 복원하지 못합니다.')
            for i, person in enumerate(source):
                try:
                    pose, notes = _openpose_person(person, raw)
                    poses.append(_pose(f'{title} / {i+1}', pose))
                    warnings.extend(f'{i+1}: {note}' for note in notes)
                except ValueError as error:
                    rejected.append(dict(index=i, reason=str(error)))
        elif isinstance(raw, list) and raw and isinstance(raw[0], list):
            # The pinned source has 77 slots; a body-identical truncation has
            # 75. Unused hand/face slots may be null in real source samples.
            # Other arrays/foreign bone indices cannot be inferred safely.
            source = [raw] if len(raw) in (75, 77) and len(raw[0]) == 3 else raw
            if not 1 <= len(source) <= MAX_IMPORT_POSES:
                raise ValueError('Import 1–2000 positional samples at a time.')
            kind = 'open-pose-editor.positions'
            warnings.append('Position-only retargeting keeps body directions; finger articulation and axial twist are unavailable. / 관절 위치로 신체 방향만 변환합니다. 손가락 회전과 축 비틀림은 복원할 수 없습니다.')
            for i, sample in enumerate(source):
                try:
                    if not isinstance(sample, list) or len(sample) not in (75, 77):
                        raise ValueError('Open Pose Editor positional sample needs 75 or 77 slots.')
                    array = _array([sample[j] for j in POSITION_MAPPING.values()],
                                   (len(POSITION_MAPPING), 3), 'Open Pose Editor body coordinates')
                    points = dict(zip(POSITION_MAPPING, array))
                    torso = np.linalg.norm(points['neck'] - points['pelvis'])
                    if torso < 1e-8:
                        raise ValueError('Collapsed torso.')
                    for side in ('left', 'right'):
                        for a, b in [('shoulder', 'elbow'), ('elbow', 'wrist'), ('hip', 'knee'), ('knee', 'ankle')]:
                            if not .08 <= np.linalg.norm(points[side+'_'+a]-points[side+'_'+b]) / torso <= 3:
                                raise ValueError('Collapsed/invalid limb proportions.')
                    poses.append(_pose(f'{title} / {i+1:04}', retarget_points(points)))
                except ValueError as error:
                    rejected.append(dict(index=i, reason=str(error)))
        else:
            raise ValueError('Unsupported pose format. Use RS catalogue/scene JSON, OpenPose COCO-18/BODY-25 JSON, Yu Zhu Open Pose Editor scenes/positional samples, or named BVH skeletons. FBX, VMD/VPD and Blender files require a separate model/rig converter. / 지원하지 않는 포즈 형식입니다. RS·OpenPose·Open Pose Editor JSON 또는 BVH를 사용하세요. FBX·VMD/VPD·Blender는 별도 모델·리그 변환이 필요합니다.')
    if not poses:
        reason = rejected[0]['reason'] if rejected else 'Empty pose file.'
        raise ValueError('No usable poses. / 가져올 수 있는 포즈가 없습니다. ' + reason)
    if rejected:
        warnings.append(f'{len(rejected)} invalid poses skipped. / 잘못된 포즈 {len(rejected)}개를 제외했습니다.')
    return dict(format=kind, poses=poses, warnings=list(dict.fromkeys(warnings)), rejected=rejected)
