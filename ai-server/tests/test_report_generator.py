import pytest
from unittest.mock import AsyncMock, patch
from src.llm.report_generator import generate_periodic_report
from src.models.report import AnalysisReport

@pytest.mark.asyncio
async def test_generate_periodic_report_success():
    mock_conn = AsyncMock()
    # fetchrow calls in order: prod, marginal, avail, mtbf
    mock_conn.fetchrow.side_effect = [
        {'total_lots': 10, 'avg_yield': 99.1, 'min_yield': 98.0, 'max_yield': 100.0, 'total_fail': 50, 'avg_uph': 1200.0},
        {'cnt': 2},
        {'avg_availability_pct': 95.0, 'total_downtime_min': 30.0},
        {'avg_mtbf_hours': 48.0},
    ]
    # fetch calls in order: fail_reason, recipe, equip, oracle_dist, alarm
    mock_conn.fetch.side_effect = [
        [{'reason_code': 'E001', 'count': 5}],
        [{'recipe_id': 'R1', 'avg_yield': 99.5, 'total_lots': 5}],
        [{'equipment_id': 'E1', 'avg_yield': 98.8, 'avg_uph': 1100.0}],
        [{'judgment': 'PASS', 'cnt': 8}, {'judgment': 'WARNING', 'cnt': 2}],
        [{'equipment_id': 'E1', 'alarm_count': 3}],
    ]

    mock_llm_response = """
    {
        "summary": "Overall performance is stable.",
        "insights": [
            {"severity": "info", "category": "yield", "message": "Yield is high.", "evidence": ["99.1% avg"]}
        ],
        "recommendations": ["Maintain current settings."]
    }
    """

    with patch("src.db.pool.db_pool.get_pool") as mock_get_pool, \
         patch("src.llm.client.llm_client.get_completion", new_callable=AsyncMock) as mock_llm:

        mock_get_pool.return_value.acquire.return_value.__aenter__.return_value = mock_conn
        mock_llm.return_value = mock_llm_response

        report = await generate_periodic_report("daily", 1)

        assert isinstance(report, AnalysisReport)
        assert report.reportType == "daily"
        assert report.metrics.totalLots == 10
        assert report.metrics.judgmentDistribution == {'PASS': 8, 'WARNING': 2}
        assert report.metrics.marginalCount == 2
        assert report.metrics.avgAvailabilityPct == 95.0
        assert report.metrics.totalDowntimeMin == 30.0
        assert report.metrics.avgMtbfHours == 48.0
        assert report.metrics.equipmentBreakdown[0].alarmCount == 3
        assert report.summary == "Overall performance is stable."
        assert len(report.insights) == 1
        assert report.recommendations[0] == "Maintain current settings."

@pytest.mark.asyncio
async def test_generate_periodic_report_llm_failure():
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = [
        {'total_lots': 0, 'avg_yield': 0, 'min_yield': 0, 'max_yield': 0, 'total_fail': 0, 'avg_uph': 0},
        {'cnt': 0},
        {'avg_availability_pct': None, 'total_downtime_min': None},
        {'avg_mtbf_hours': None},
    ]
    mock_conn.fetch.side_effect = [[], [], [], [], []]

    with patch("src.db.pool.db_pool.get_pool") as mock_get_pool, \
         patch("src.llm.client.llm_client.get_completion", new_callable=AsyncMock) as mock_llm:

        mock_get_pool.return_value.acquire.return_value.__aenter__.return_value = mock_conn
        mock_llm.side_effect = Exception("LLM Error")

        report = await generate_periodic_report("daily", 1)

        assert "AI 분석 실패" in report.summary
        assert len(report.insights) == 0
