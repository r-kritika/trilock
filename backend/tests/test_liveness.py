"""Face liveness logic, tested with a small 3D head model instead of a camera.

Landmarks: right eye, left eye, nose tip, right mouth corner, left mouth corner (units: eye distance).
A real head is rotated about a vertical axis behind the face, so the protruding nose moves relative to
the eyes. A flat photo has all five points in one plane, so rotating it only scales x. These tests check
the decision code; they do not show the check works with a real camera or detector."""
import numpy as np
import pytest

from app.biometrics.liveness import FaceLiveness, LivenessConfig, parallax_residual, yaw_proxy

HEAD = np.array([[-0.5, 0.0, 0.0], [0.5, 0.0, 0.0], [0.0, 0.55, 0.55], [-0.35, 1.1, 0.1], [0.35, 1.1, 0.1]])


def project(points3d, yaw_deg, flat=False, noise=0.0, rng=None):
    th = np.deg2rad(yaw_deg)
    pts = points3d.copy()
    if flat:
        pts[:, 2] = 0.0                                    # a photo: every point on one plane
    z = pts[:, 2] - 0.6                                    # pivot behind the face
    x = pts[:, 0] * np.cos(th) + z * np.sin(th)
    out = np.stack([x, pts[:, 1]], axis=1) * 100 + [320, 200]
    if noise and rng is not None:
        out = out + rng.normal(0, noise * 100, out.shape)  # detector jitter, in eye-distance units
    return out


class FakeFace:
    """Stands in for FaceModule: a 'frame' is just an index into prepared landmark sets."""
    def __init__(self, sets, identity=None):
        self.sets, self.identity = sets, identity or {}

    def landmarks(self, data):
        i = int(data.decode())
        pts = self.sets[i]
        return None if pts is None else (pts, np.array([i]), np.array([i]))

    def embedding_for(self, img, row):
        return self.identity.get(int(row[0]), np.ones(8, np.float32))


def run(sets, direction="left", cfg=None, identity=None):
    live = FaceLiveness(FakeFace(sets, identity), cfg)
    return live.check([str(i).encode() for i in range(len(sets))], direction)


def turn(max_deg, n=10, flat=False, noise=0.03, seed=0):
    rng = np.random.default_rng(seed)
    return [project(HEAD, max_deg * k / (n - 1), flat, noise, rng) for k in range(n)]


def test_yaw_proxy_signs_follow_the_convention():
    left, right = project(HEAD, 30), project(HEAD, -30)
    assert yaw_proxy(left) > 0.2 > -0.2 > yaw_proxy(right) and abs(yaw_proxy(project(HEAD, 0))) < 0.05


def test_parallax_is_large_for_a_head_and_near_zero_for_a_flat_photo():
    a = project(HEAD, 0)
    assert parallax_residual(a, project(HEAD, 35)) > 0.25
    assert parallax_residual(project(HEAD, 0, flat=True), project(HEAD, 35, flat=True)) < 0.02


def test_real_turn_in_the_requested_direction_passes():
    r = run(turn(35), "left")
    assert r.ok and r.frame_index == 0 and r.details["yaw_change"] >= 0.25 and r.details["parallax"] >= 0.15
    assert run([project(HEAD, -35 * k / 9, noise=0.03, rng=np.random.default_rng(k)) for k in range(10)], "right").ok


def test_wrong_direction_is_reported_as_such():
    r = run(turn(35), "right")
    assert not r.ok and r.code == "wrong_direction"


def test_no_movement_fails():
    r = run([project(HEAD, 0, noise=0.03, rng=np.random.default_rng(k)) for k in range(10)])
    assert not r.ok and r.code == "no_head_turn"


@pytest.mark.parametrize("seed", range(20))
def test_tilted_flat_photo_does_not_pass(seed):
    """A photo tilted toward the camera moves all landmarks as a plane. Even with detector noise it must not
    produce a yaw change of 0.25 with parallax 0.15 (checked across noise seeds)."""
    r = run(turn(40, flat=True, seed=seed), "left")
    assert not r.ok and r.code in ("no_head_turn", "flat_face_suspected")


def test_swapping_between_two_photos_is_an_abrupt_change():
    frontal, turned = project(HEAD, 0), project(HEAD, 35)
    sets = [frontal] * 5 + [turned] * 5                    # two real photos of the owner, shown one after the other
    r = run(sets)
    assert not r.ok and r.code == "abrupt_change"


def test_face_lost_in_many_frames_fails():
    sets = turn(35)
    for i in (2, 3, 4, 5, 6, 7):
        sets[i] = None
    r = run(sets)
    assert not r.ok and r.code == "face_lost"


def test_another_person_appearing_mid_challenge_fails():
    sets = turn(35)
    ident = {k: np.array([1.0, 0, 0, 0, 0, 0, 0, 0], np.float32) for k in range(10)}
    ident.update({k: np.array([0, 1.0, 0, 0, 0, 0, 0, 0], np.float32) for k in range(5, 10)})    # orthogonal identity
    r = run(sets, identity=ident)
    assert not r.ok and r.code == "face_changed"


def test_frame_count_limits_and_bad_direction():
    assert run(turn(35, n=3)).code == "frame_count"
    assert run(turn(35, n=30)).code == "frame_count"
    assert run(turn(35), direction="up").code == "bad_challenge"


def test_thresholds_are_configurable():
    strict = LivenessConfig(yaw_min=0.9)
    assert run(turn(35), cfg=strict).code == "no_head_turn"
