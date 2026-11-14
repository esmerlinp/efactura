import io
import os
import zipfile

from unittest.mock import patch


def _login_session(client, company_id="company-download-test"):
    with client.session_transaction() as session:
        session["user"] = {"ownerUID": "owner-1"}
        session["selected_owner_uid"] = "owner-1"
        session["selected_company_id"] = company_id


def test_step2_group4_xml_download_uses_absolute_evidence_path(client, tmp_path):
    company_id = "company-download-test"
    run_number = 7
    xml_dir = tmp_path / company_id / "step2" / f"run{run_number}" / "xml"
    xml_dir.mkdir(parents=True)
    xml_path = xml_dir / "E320000000001_manual_signed.xml"
    xml_path.write_bytes(b"<ECF>signed</ECF>")

    _login_session(client, company_id)
    with patch("app.api.v1.certificacion.DgiiCertService.get_process", return_value={
        "steps": {"2": {"current_run": run_number}}
    }), patch(
        "app.api.v1.certificacion._get_evidence_dir_path",
        return_value=str(xml_path.parent),
    ):
        response = client.get(
            "/api/v1/certificacion/step-2/download/E320000000001"
            f"?run={run_number}"
        )

    assert response.status_code == 200
    assert response.data == b"<ECF>signed</ECF>"
    assert response.headers["Content-Disposition"].endswith(
        'filename=E320000000001_manual_signed.xml'
    )


def test_step2_zip_download_contains_group4_xml(client, tmp_path):
    company_id = "company-download-test"
    run_number = 7
    evidence_dir = tmp_path / company_id / "step2" / f"run{run_number}"
    xml_dir = evidence_dir / "xml"
    xml_dir.mkdir(parents=True)
    (xml_dir / "E320000000001_manual_signed.xml").write_bytes(b"<ECF/>")

    _login_session(client, company_id)
    with patch("app.api.v1.certificacion.DgiiCertService.get_process", return_value={
        "steps": {"2": {"current_run": run_number}}
    }), patch(
        "app.services.dgii_cert_service._get_evidence_dir",
        return_value=str(evidence_dir),
    ):
        response = client.get(
            "/api/v1/certificacion/step-2/download-all"
            f"?run={run_number}"
        )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert "xml/E320000000001_manual_signed.xml" in archive.namelist()
        assert archive.read("xml/E320000000001_manual_signed.xml") == b"<ECF/>"


def test_step2_zip_download_contains_e32_filename(client, tmp_path):
    company_id = "company-download-test"
    run_number = 7
    evidence_dir = tmp_path / company_id / "step2" / f"run{run_number}"
    xml_dir = evidence_dir / "xml"
    xml_dir.mkdir(parents=True)
    (xml_dir / "E320000000011_e32_firmado.xml").write_bytes(b"<ECF/>")

    _login_session(client, company_id)
    with patch("app.api.v1.certificacion.DgiiCertService.get_process", return_value={
        "steps": {"2": {"current_run": run_number}}
    }), patch(
        "app.services.dgii_cert_service._get_evidence_dir",
        return_value=str(evidence_dir),
    ):
        response = client.get(
            "/api/v1/certificacion/step-2/download-all"
            f"?run={run_number}"
        )

    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
        assert "xml/E320000000011_e32_firmado.xml" in archive.namelist()


def test_step2_zip_download_falls_back_to_latest_evidence_run(client, tmp_path):
    company_id = "company-download-test"
    latest_dir = tmp_path / company_id / "step2" / "run9"
    xml_dir = latest_dir / "xml"
    xml_dir.mkdir(parents=True)
    (xml_dir / "E320000000011_manual_signed.xml").write_bytes(b"<ECF/>")

    _login_session(client, company_id)
    with patch("app.api.v1.certificacion.DgiiCertService.get_process", return_value={
        "steps": {"2": {"current_run": 3}}
    }), patch(
        "app.api.v1.certificacion._get_evidence_dir_path",
        side_effect=lambda _company, _step, run: str(
            tmp_path / company_id / "step2" / f"run{run}"
        ),
    ), patch(
        "app.services.dgii_cert_service._get_evidence_dir",
        return_value=str(latest_dir),
    ):
        response = client.get("/api/v1/certificacion/step-2/download-all?run=3")

    assert response.status_code == 200
    assert "evidencias_paso2_run9.zip" in response.headers["Content-Disposition"]


def test_step2_group4_xml_download_accepts_e32_filename(client, tmp_path):
    company_id = "company-download-test"
    run_number = 7
    xml_dir = tmp_path / company_id / "step2" / f"run{run_number}" / "xml"
    xml_dir.mkdir(parents=True)
    xml_path = xml_dir / "E320000000011_e32_firmado.xml"
    xml_path.write_bytes(b"<ECF>e32</ECF>")

    _login_session(client, company_id)
    with patch("app.api.v1.certificacion.DgiiCertService.get_process", return_value={
        "steps": {"2": {"current_run": run_number}}
    }), patch(
        "app.api.v1.certificacion._get_evidence_dir_path",
        return_value=str(xml_path.parent),
    ):
        response = client.get(
            "/api/v1/certificacion/step-2/download/E320000000011"
            f"?run={run_number}"
        )

    assert response.status_code == 200
    assert response.data == b"<ECF>e32</ECF>"
    assert response.headers["Content-Disposition"].endswith(
        'filename=E320000000011_e32_firmado.xml'
    )
