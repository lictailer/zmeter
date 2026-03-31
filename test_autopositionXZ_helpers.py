import sys
import types
import unittest

import numpy as np
from scipy import ndimage, signal

# try:
from autofocus_xuguo.autopositionXZ_helpers import fit_offset
# except ModuleNotFoundError as exc:
#     if exc.name != "skimage":
#         raise

#     def _fallback_phase_cross_correlation(reference_image, moving_image, upsample_factor=1):
#         del upsample_factor
#         reference_filled = np.nan_to_num(reference_image, nan=0.0)
#         moving_filled = np.nan_to_num(moving_image, nan=0.0)
#         correlation = signal.correlate(
#             reference_filled,
#             moving_filled,
#             mode="full",
#             method="fft",
#         )
#         maxima = np.unravel_index(np.argmax(correlation), correlation.shape)
#         shifts = np.array(
#             [
#                 maxima[0] - (moving_image.shape[0] - 1),
#                 maxima[1] - (moving_image.shape[1] - 1),
#             ],
#             dtype=float,
#         )
#         error = 0.0
#         return shifts, error, 0.0

#     skimage_module = types.ModuleType("skimage")
#     registration_module = types.ModuleType("skimage.registration")
#     registration_module.phase_cross_correlation = _fallback_phase_cross_correlation
#     skimage_module.registration = registration_module
#     sys.modules.setdefault("skimage", skimage_module)
#     sys.modules["skimage.registration"] = registration_module

#     from autofocus_xuguo.autopositionXZ_helpers import fit_offset


def make_gaussian_map(
    size: int = 101,
    *,
    amplitude: float = 1.0,
    sigma_x: float = 11.0,
    sigma_y: float = 8.0,
) -> np.ndarray:
    center = (size - 1) / 2.0
    coords = np.arange(size, dtype=float) - center
    x_grid, y_grid = np.meshgrid(coords, coords)
    exponent = -0.5 * ((x_grid / sigma_x) ** 2 + (y_grid / sigma_y) ** 2)
    return amplitude * np.exp(exponent)


def build_shifted_test_maps(
    rng: np.random.Generator,
    *,
    size: int = 101,
    scale_factor: float = 0.8,
    reference_noise_sigma: float = 0.02,
    new_noise_sigma: float = 0.025,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    base_map = make_gaussian_map(size=size)

    shift_x = int(rng.integers(-12, 13))
    shift_y = int(rng.integers(-12, 13))

    reference_map = base_map + rng.normal(0.0, reference_noise_sigma, size=(size, size))
    shifted_scaled_map = ndimage.shift(
        scale_factor * base_map,
        shift=(shift_y, shift_x),
        order=1,
        mode="constant",
        cval=0.0,
    )
    new_map = shifted_scaled_map + rng.normal(0.0, new_noise_sigma, size=(size, size))

    return reference_map, new_map, shift_x, shift_y


class FitOffsetSyntheticMapTests(unittest.TestCase):
    def test_fit_offset_recovers_random_pixel_shift_on_noisy_gaussian_maps(self):
        rng = np.random.default_rng(20260323)
        x_values = np.arange(101, dtype=float)
        y_values = np.arange(101, dtype=float)
        recovered_errors = []
        failure_messages = []
        trial_reports = []

        for trial_index in range(12):
            reference_map, new_map, true_shift_x, true_shift_y = build_shifted_test_maps(rng)

            result = fit_offset(
                reference_map,
                new_map,
                x_values=x_values,
                y_values=y_values,
                upsample_factor=20,
                quality_threshold=0.6,
            )

            with self.subTest(
                trial=trial_index,
                true_shift_x=true_shift_x,
                true_shift_y=true_shift_y,
            ):
                if not result.success:
                    failure_messages.append(
                        "trial="
                        f"{trial_index}, true_shift=({true_shift_x}, {true_shift_y}), "
                        f"recovered_shift=({result.shift_x_pixels}, {result.shift_y_pixels}), "
                        f"quality={result.quality:.3f}, message={result.message}"
                    )
                self.assertTrue(result.success, msg=result.message)
                self.assertIsNotNone(result.offset_x)
                self.assertIsNotNone(result.offset_y)
                self.assertIsNotNone(result.shift_x_pixels)
                self.assertIsNotNone(result.shift_y_pixels)

                offset_error_x = abs(result.offset_x - true_shift_x)
                offset_error_y = abs(result.offset_y - true_shift_y)
                alignment_error_x = abs(result.shift_x_pixels + true_shift_x)
                alignment_error_y = abs(result.shift_y_pixels + true_shift_y)

                trial_reports.append(
                    {
                        "trial": trial_index,
                        "true_shift_x": float(true_shift_x),
                        "true_shift_y": float(true_shift_y),
                        "fit_shift_x": float(result.shift_x_pixels),
                        "fit_shift_y": float(result.shift_y_pixels),
                        "offset_x": float(result.offset_x),
                        "offset_y": float(result.offset_y),
                        "offset_error_x": float(offset_error_x),
                        "offset_error_y": float(offset_error_y),
                        "quality": float(result.quality),
                        "success": bool(result.success),
                    }
                )

                recovered_errors.append(
                    (
                        trial_index,
                        true_shift_x,
                        true_shift_y,
                        result.offset_x,
                        result.offset_y,
                        result.quality,
                    )
                )

                self.assertLessEqual(offset_error_x, 0.35)
                self.assertLessEqual(offset_error_y, 0.35)
                self.assertLessEqual(alignment_error_x, 0.35)
                self.assertLessEqual(alignment_error_y, 0.35)
                self.assertGreaterEqual(result.quality, 0.9)

        if not recovered_errors:
            self.fail(
                "fit_offset did not succeed on any trial.\n"
                + "\n".join(failure_messages)
            )

        self._print_trial_report(trial_reports)

        worst_trial = max(
            recovered_errors,
            key=lambda item: max(abs(item[3] - item[1]), abs(item[4] - item[2])),
        )
        worst_error = max(abs(worst_trial[3] - worst_trial[1]), abs(worst_trial[4] - worst_trial[2]))

        self.assertLessEqual(
            worst_error,
            0.35,
            msg=(
                "Worst-case offset recovery exceeded tolerance: "
                f"trial={worst_trial[0]}, true_shift=({worst_trial[1]}, {worst_trial[2]}), "
                f"recovered_offset=({worst_trial[3]:.3f}, {worst_trial[4]:.3f}), "
                f"quality={worst_trial[5]:.3f}"
            ),
        )

    @staticmethod
    def _print_trial_report(trial_reports):
        print("\nDetailed fit_offset report")
        print(f"Trials: {len(trial_reports)}")
        print(f"Successful fits: {sum(report['success'] for report in trial_reports)}")
        print(f"Mean quality: {np.mean([report['quality'] for report in trial_reports]):.6f}")
        print(f"Min quality: {min(report['quality'] for report in trial_reports):.6f}")
        print(
            "Max offset error: "
            f"x={max(report['offset_error_x'] for report in trial_reports):.3f} px, "
            f"y={max(report['offset_error_y'] for report in trial_reports):.3f} px"
        )
        for report in trial_reports:
            print(
                "trial={trial:02d} true=({true_shift_x:>5.1f},{true_shift_y:>5.1f}) "
                "fit_shift=({fit_shift_x:>5.1f},{fit_shift_y:>5.1f}) "
                "offset=({offset_x:>5.1f},{offset_y:>5.1f}) "
                "offset_err=({offset_error_x:.3f},{offset_error_y:.3f}) "
                "quality={quality:.6f} success={success}".format(**report)
            )


if __name__ == "__main__":
    unittest.main()
