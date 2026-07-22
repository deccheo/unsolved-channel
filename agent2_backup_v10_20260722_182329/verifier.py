import json
from pydantic import BaseModel, Field
from config import GEMINI_API_KEY, GEMINI_MODEL

class Verification(BaseModel):
    real_case: bool
    unresolved: bool
    enough_sources: bool
    source_count_used: int = Field(ge=0)
    verification_score: int = Field(ge=0,le=100)
    verified_summary: str
    confirmed_facts: list[str]
    unsupported_claims: list[str]
    conflicts: list[str]
    legal_risk: str
    recommendation: str

def _client():
    if not GEMINI_API_KEY: raise RuntimeError('Thiếu GEMINI_API_KEY')
    from google import genai
    return genai.Client(api_key=GEMINI_API_KEY)

def verify(case,sources) -> dict:
    if not sources: raise ValueError('Không có nguồn để kiểm chứng')
    from google.genai import types
    source_text=[]
    for i,s in enumerate(sources,1):
        source_text.append(f"SOURCE {i}\nTITLE: {s['title']}\nPUBLISHER: {s['source_name']}\nURL: {s['url']}\nRELIABILITY: {s['reliability_score']}\nRELEVANCE: {s['relevance_score']}\nTEXT: {(s['extracted_text'] or '')[:7000]}")
    prompt=f'''You are a strict fact-checking editor for an English documentary channel. Use only supplied sources.
CASE: {case['case_name'] or case['title']} | COUNTRY: {case['country'] or ''}
INITIAL SUMMARY: {case['ai_summary'] or case['article_summary'] or ''}
SOURCES:\n{chr(10).join(source_text)}
Rules:
- real_case=true only for a real person or criminal investigation.
- unresolved=true only when the latest evidence says the core case remains open.
- enough_sources=true for one official source, one reputable detailed news source, or two independent secondary sources.
- Never accuse an uncharged person. Put uncertainty in unsupported_claims.
- recommendation: VERIFIED, NEEDS_REVIEW, or REJECTED. legal_risk: LOW, MEDIUM, or HIGH.
'''
    response=_client().models.generate_content(model=GEMINI_MODEL,contents=prompt,config=types.GenerateContentConfig(temperature=0.0,response_mime_type='application/json',response_schema=Verification))
    if not getattr(response,'text',None): raise RuntimeError('Gemini trả về nội dung rỗng')
    result=Verification.model_validate(json.loads(response.text)).model_dump()
    result['recommendation']=result['recommendation'].strip().upper()
    result['legal_risk']=result['legal_risk'].strip().upper()
    if result['recommendation'] not in {'VERIFIED','NEEDS_REVIEW','REJECTED'}: result['recommendation']='NEEDS_REVIEW'
    if result['legal_risk'] not in {'LOW','MEDIUM','HIGH'}: result['legal_risk']='MEDIUM'
    result['source_count_used']=min(result['source_count_used'],len(sources))
    return result
