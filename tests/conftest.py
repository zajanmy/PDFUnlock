"""Generated documents for known-password decryption integration tests."""

import pikepdf
import pytest


@pytest.fixture
def make_pdf(tmp_path):
    def create(name, user=None, owner="ownerpw"):
        target = tmp_path / name
        with pikepdf.new() as document:
            document.add_blank_page(page_size=(200, 200))
            options = {}
            if user is not None:
                options["encryption"] = pikepdf.Encryption(
                    user=user, owner=owner,
                    allow=pikepdf.Permissions(extract=False, print_highres=False),
                )
            document.save(target, **options)
        return target
    return create


@pytest.fixture
def plain_pdf(make_pdf):
    return make_pdf("plain.pdf")


@pytest.fixture
def user_pw_pdf(make_pdf):
    return make_pdf("user.pdf", user="secret42")


@pytest.fixture
def owner_pw_pdf(make_pdf):
    return make_pdf("owner.pdf", user="")
