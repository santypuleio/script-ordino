"""Tests unitarios de scoring y clasificación de outreach (sin Selenium)."""

import unittest

from instagram_profile import (
    argentina_profile_verdict,
    build_outreach_message,
    classify_pitch_type,
    include_argentina_profile,
    infer_sale_niche,
    is_argentina_focused_hashtag,
    merge_hashtag_user_profile,
    needs_profile_api_fetch,
    score_bio,
    username_suggests_foreign,
)


class TestScoreBio(unittest.TestCase):
    def test_positive_keywords(self) -> None:
        bio = "Tienda online de remeras. Envios a todo el pais. Catalogo en WhatsApp."
        self.assertGreaterEqual(score_bio(bio), 4)

    def test_negative_keywords(self) -> None:
        bio = "Meme page / humor. No vendo nada."
        self.assertLess(score_bio(bio), 2)

    def test_mixed_bio(self) -> None:
        bio = "Emprendimiento de perfumes arabes. Ventas por Instagram."
        self.assertGreaterEqual(score_bio(bio), 4)

    def test_retro_store_bio(self) -> None:
        bio = "Tienda retro Game Boy y consolas. Envios a todo el pais."
        self.assertGreaterEqual(score_bio(bio), 4)


class TestClassifyPitchType(unittest.TestCase):
    def test_no_url(self) -> None:
        self.assertEqual(classify_pitch_type(""), "no_website")
        self.assertEqual(classify_pitch_type(None), "no_website")

    def test_whatsapp_only(self) -> None:
        self.assertEqual(classify_pitch_type("https://wa.me/5491112345678"), "no_website")

    def test_linktree(self) -> None:
        self.assertEqual(classify_pitch_type("https://linktr.ee/mitienda"), "no_website")

    def test_own_website(self) -> None:
        self.assertEqual(
            classify_pitch_type("https://mitienda.com.ar/productos"),
            "has_website",
        )

    def test_shopify(self) -> None:
        self.assertEqual(
            classify_pitch_type("https://mitienda.myshopify.com"),
            "has_website",
        )


class TestArgentinaFilter(unittest.TestCase):
    def test_argentina_hashtag_marker(self) -> None:
        self.assertTrue(is_argentina_focused_hashtag("emprendedoresargentina"))
        self.assertFalse(is_argentina_focused_hashtag("retrogaming"))

    def test_foreign_username(self) -> None:
        self.assertTrue(username_suggests_foreign("feriaretro.cl")[0])
        self.assertTrue(username_suggests_foreign("vibe.vzla")[0])

    def test_argentina_bio(self) -> None:
        profile = {
            "bio": "Tienda en Buenos Aires. Envíos a todo el país. WhatsApp +54 9 11...",
            "external_url": "https://mitienda.com.ar",
            "public_phone_country_code": "54",
            "city_name": "",
        }
        self.assertEqual(argentina_profile_verdict(profile)[0], "ar")

    def test_foreign_bio(self) -> None:
        profile = {
            "bio": "Envíos desde México CDMX",
            "external_url": "https://tienda.com.mx",
            "public_phone_country_code": "52",
            "city_name": "",
        }
        self.assertEqual(argentina_profile_verdict(profile)[0], "foreign")

    def test_foreign_username_in_verdict(self) -> None:
        profile = {"bio": "Tienda retro", "external_url": "", "public_phone_country_code": ""}
        self.assertEqual(
            argentina_profile_verdict(profile, username="tienda.cl")[0], "foreign"
        )

    def test_unknown_strict_skips(self) -> None:
        import os

        profile = {
            "bio": "Tienda online de accesorios",
            "external_url": "",
            "public_phone_country_code": "",
            "city_name": "",
        }
        self.assertEqual(argentina_profile_verdict(profile)[0], "unknown")
        old = os.environ.get("OUTREACH_REQUIRE_ARGENTINA")
        old_s = os.environ.get("OUTREACH_ARGENTINA_STRICT")
        try:
            os.environ["OUTREACH_REQUIRE_ARGENTINA"] = "1"
            os.environ["OUTREACH_ARGENTINA_STRICT"] = "1"
            self.assertFalse(include_argentina_profile(profile)[0])
        finally:
            if old is None:
                os.environ.pop("OUTREACH_REQUIRE_ARGENTINA", None)
            else:
                os.environ["OUTREACH_REQUIRE_ARGENTINA"] = old
            if old_s is None:
                os.environ.pop("OUTREACH_ARGENTINA_STRICT", None)
            else:
                os.environ["OUTREACH_ARGENTINA_STRICT"] = old_s


class TestDiscoverFast(unittest.TestCase):
    def test_needs_fetch_without_id(self) -> None:
        self.assertTrue(needs_profile_api_fetch({"username": "x", "id": ""}))

    def test_skip_fetch_when_complete(self) -> None:
        raw = {
            "id": "123",
            "username": "tienda",
            "bio": "Tienda online de remeras con envios",
            "external_url": "https://wa.me/54911",
        }
        self.assertFalse(needs_profile_api_fetch(raw))

    def test_merge_profile(self) -> None:
        merged = merge_hashtag_user_profile(
            {"username": "a", "id": "1", "bio": "old"},
            {"username": "a", "id": "99", "bio": "new bio", "followers_count": 100},
        )
        self.assertEqual(merged["id"], "99")
        self.assertEqual(merged["bio"], "new bio")


class TestBuildMessage(unittest.TestCase):
    def test_single_template(self) -> None:
        msg = build_outreach_message("labotica", "no_website")
        self.assertIn("Hola!", msg)
        self.assertIn("los productos que venden", msg)
        self.assertIn("stock", msg)
        self.assertIn("planillas", msg)

    def test_niche_perfumes(self) -> None:
        self.assertEqual(infer_sale_niche("Perfumes árabes y esencias"), "perfumes")
        msg = build_outreach_message(
            "tienda", "no_website", bio="Perfumes árabes y esencias"
        )
        self.assertIn("los perfumes que venden", msg)

    def test_niche_retro(self) -> None:
        msg = build_outreach_message(
            "retroshop", "no_website", bio="Tienda retro Game Boy y consolas"
        )
        self.assertIn("los productos retro que venden", msg)

    def test_niche_default(self) -> None:
        msg = build_outreach_message("shop", "has_website", bio="")
        self.assertIn("los productos que venden", msg)


if __name__ == "__main__":
    unittest.main()
