"""
DOCX 파일 처리 유틸리티
"""
import io
import re
from docx import Document


def extract_text_with_separated_tables(file_content: bytes) -> dict:
    """
    DOCX 파일에서 텍스트를 추출하되, 테이블 헤더와 데이터를 분리합니다.
    
    Args:
        file_content: DOCX 파일의 바이트 내용
        
    Returns:
        {
            'paragraphs': 문단들의 리스트,
            'table_headers': 각 테이블 첫 번째 행들의 리스트,
            'table_data_rows': 각 테이블 나머지 행들의 리스트,
            'full_text': 전체 텍스트
        }
    """
    try:
        # 바이트 데이터를 메모리 스트림으로 변환
        file_stream = io.BytesIO(file_content)
        
        # Document 객체 생성
        doc = Document(file_stream)
        
        # 문단 추출
        paragraphs = []
        for paragraph in doc.paragraphs:
            if paragraph.text.strip():  # 빈 줄 제외
                paragraphs.append(paragraph.text.strip())
        
        # 테이블에서 헤더와 데이터 분리 추출
        table_headers = []  # 각 테이블의 첫 번째 행(헤더)
        table_data_rows = []  # 각 테이블의 나머지 행들
        all_tables = []  # 전체 테이블 (기존 형태)
        
        for table_idx, table in enumerate(doc.tables):
            table_text = []
            
            for row_idx, row in enumerate(table.rows):
                row_text = []
                for cell in row.cells:
                    if cell.text.strip():
                        row_text.append(cell.text.strip())
                
                if row_text:
                    row_content = " | ".join(row_text)
                    table_text.append(row_content)
                    
                    # 첫 번째 행은 헤더로 분류
                    if row_idx == 0:
                        table_headers.append({
                            'table_index': table_idx,
                            'content': row_content
                        })
                    else:
                        # 나머지 행들은 데이터 행으로 분류
                        table_data_rows.append({
                            'table_index': table_idx,
                            'row_index': row_idx,
                            'content': row_content
                        })
            
            if table_text:
                all_tables.append("\n".join(table_text))
        
        # 전체 텍스트 결합
        all_text = []
        
        if paragraphs:
            all_text.append("=== 문서 내용 ===")
            all_text.extend(paragraphs)
        
        if all_tables:
            all_text.append("\n=== 표 내용 ===")
            all_text.extend(all_tables)
        
        return {
            'paragraphs': paragraphs,
            'table_headers': table_headers,
            'table_data_rows': table_data_rows,
            'full_text': "\n".join(all_text)
        }
        
    except Exception as e:
        raise Exception(f"DOCX 분리 처리 중 오류 발생: {str(e)}")


def filter_duplicate_rows(table_data_rows: list) -> dict:
    """
    테이블 데이터 행에서 중복 제거 및 통계 정보를 제공합니다.
    
    Args:
        table_data_rows: extract_text_with_separated_tables에서 반환된 table_data_rows
        
    Returns:
        {
            'unique_rows': 중복 제거된 행들,
            'duplicate_stats': 각 행의 반복 횟수 통계
        }
    """
    try:
        content_count = {}
        unique_rows = []
        
        for row_data in table_data_rows:
            content = row_data['content'].strip()  # 앞뒤 화이트스페이스 제거
            content = re.sub(r'\s+', ' ', content)  # 연속된 공백을 하나로 통합
            
            if content not in content_count:
                # 정리된 content로 새로운 row_data 생성
                cleaned_row_data = row_data.copy()
                cleaned_row_data['content'] = content
                
                content_count[content] = {
                    'count': 1,
                    'first_occurrence': cleaned_row_data
                }
                unique_rows.append(cleaned_row_data)
            else:
                content_count[content]['count'] += 1
        
        # 통계 정보 생성
        duplicate_stats = {}
        for content, info in content_count.items():
            if info['count'] > 1:
                duplicate_stats[content] = info['count']
        
        return {
            'unique_rows': unique_rows,
            'duplicate_stats': duplicate_stats,
            'total_unique': len(unique_rows),
            'total_duplicates': len(duplicate_stats)
        }
        
    except Exception as e:
        raise Exception(f"중복 필터링 중 오류 발생: {str(e)}")
