"""
DOCX 파일 처리 유틸리티
"""
import io
from docx import Document


def extract_text_from_docx(file_content: bytes) -> str:
    """
    DOCX 파일 내용에서 텍스트를 추출합니다.
    
    Args:
        file_content: DOCX 파일의 바이트 내용
        
    Returns:
        추출된 텍스트 문자열
    """
    try:
        # 바이트 데이터를 메모리 스트림으로 변환
        file_stream = io.BytesIO(file_content)
        
        # Document 객체 생성
        doc = Document(file_stream)
        
        # 모든 paragraph에서 텍스트 추출
        paragraphs = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():  # 빈 줄 제외
                paragraphs.append(paragraph.text.strip())
        
        # 테이블에서 텍스트 추출
        tables = []
        for table in doc.tables:
            table_text = []
            for row in table.rows:
                row_text = []
                for cell in row.cells:
                    if cell.text.strip():
                        row_text.append(cell.text.strip())
                if row_text:
                    table_text.append(" | ".join(row_text))
            if table_text:
                tables.append("\n".join(table_text))
        
        # 전체 텍스트 결합
        all_text = []
        
        if paragraphs:
            all_text.append("=== 문서 내용 ===")
            all_text.extend(paragraphs)
        
        if tables:
            all_text.append("\n=== 표 내용 ===")
            all_text.extend(tables)
        
        return "\n".join(all_text)
        
    except Exception as e:
        raise Exception(f"DOCX 파일 처리 중 오류 발생: {str(e)}")


def extract_headings_and_content(file_content: bytes) -> dict:
    """
    DOCX 파일에서 제목별로 내용을 구조화하여 추출합니다.
    
    Args:
        file_content: DOCX 파일의 바이트 내용
        
    Returns:
        제목을 키로 하는 딕셔너리
    """
    try:
        file_stream = io.BytesIO(file_content)
        doc = Document(file_stream)
        
        structured_content = {}
        current_heading = "기본 내용"
        current_content = []
        
        for paragraph in doc.paragraphs:
            # 제목 스타일 확인 (Heading 1, 2, 3 등)
            if paragraph.style.name.startswith('Heading'):
                # 이전 섹션 저장
                if current_content:
                    structured_content[current_heading] = "\n".join(current_content)
                
                # 새 섹션 시작
                current_heading = paragraph.text.strip()
                current_content = []
            else:
                # 일반 내용 추가
                if paragraph.text.strip():
                    current_content.append(paragraph.text.strip())
        
        # 마지막 섹션 저장
        if current_content:
            structured_content[current_heading] = "\n".join(current_content)
        
        return structured_content
        
    except Exception as e:
        raise Exception(f"DOCX 구조화 처리 중 오류 발생: {str(e)}")
