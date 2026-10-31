# 프로젝트 전용 Python 환경과 해시가 고정된 한국어·영어 OCR 데이터를 준비한다.
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
$taskRoot = Split-Path -Parent $PSScriptRoot
Push-Location $taskRoot
try {
    if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Python 가상환경 생성 실패.' }
    }
    & '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '의존성 설치 실패.' }
    New-Item -ItemType Directory -Force -Path 'data\models\tessdata' | Out-Null
    $taskModels = @{
        eng = '8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba'
        kor = 'f888d4038348a0c3d25151e7f452bda0d74ca275b18cab146798bcbb94084fff'
    }
    foreach ($taskLang in $taskModels.Keys) {
        $taskPath = "data\models\tessdata\$taskLang.traineddata"
        if (-not (Test-Path -LiteralPath $taskPath)) {
            Invoke-WebRequest -Uri "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/e12c65a915945e4c28e237a9b52bc4a8f39a0cec/$taskLang.traineddata" -OutFile $taskPath
        }
        if ((Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskModels[$taskLang]) {
            throw "OCR 모델 해시 불일치. 기존 파일을 덮어쓰지 않았습니다. $taskPath"
        }
    }
    '로컬 추출 환경과 OCR 데이터 준비 완료.'
} finally {
    Pop-Location
}
