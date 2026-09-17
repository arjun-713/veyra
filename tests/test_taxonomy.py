import unittest

import numpy as np

from datasets.common.taxonomy import RELLIS_LABELS, map_dataset_labels


class TaxonomyTests(unittest.TestCase):
    def test_rellis_maps_by_class_meaning_into_veyra_space(self):
        # RELLIS raw IDs from the upstream labels file.  The expected values
        # are Veyra SemanticKITTI-learning IDs, not RELLIS learning IDs.
        raw = np.array([3, 4, 5, 6, 8, 10, 12, 15, 17, 18, 19, 33], dtype=np.uint16)

        mapped = map_dataset_labels(raw, RELLIS_LABELS)

        np.testing.assert_array_equal(
            mapped, [15, 15, 18, 0, 5, 9, 13, 16, 6, 14, 15, 17]
        )

    def test_mapping_preserves_shape_contract_and_handles_large_ids_without_lut(self):
        raw = np.array([[3, 2**63 - 1], [-7, 999999999999]], dtype=np.int64)

        mapped = map_dataset_labels(raw, {3: 15})

        self.assertEqual(mapped.dtype, np.int32)
        self.assertEqual(mapped.shape, (4,))
        np.testing.assert_array_equal(mapped, [15, 0, 0, 0])

    def test_mapping_rejects_non_integral_or_non_numeric_labels(self):
        for labels in (np.array([1.5]), np.array([np.nan]), np.array(["3"])):
            with self.subTest(labels=labels):
                with self.assertRaises((TypeError, ValueError)):
                    map_dataset_labels(labels, {3: 15})


if __name__ == "__main__":
    unittest.main()
