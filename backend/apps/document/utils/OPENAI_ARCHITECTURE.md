# Arquitectura del Cliente OpenAI

## Decisión de Diseño

### ✅ Cliente Compartido (Singleton Pattern)

**Decisión:** Un solo cliente de OpenAI compartido entre todas las apps (documents, chat, evaluations).

### ¿Por qué este enfoque?

#### 1. **Eficiencia**
- **Reutilización de conexiones HTTP:** El cliente mantiene conexiones persistentes que se reutilizan
- **Menor overhead:** Una sola instancia en memoria vs múltiples
- **Mejor rendimiento:** Menos tiempo de establecimiento de conexión

#### 2. **Simplicidad**
- **Un solo punto de configuración:** La API key se configura una vez
- **Código más limpio:** No hay duplicación de lógica de inicialización
- **Fácil mantenimiento:** Cambios en un solo lugar

#### 3. **Flexibilidad Mantenida**
- **Configuración por llamada:** Cada app puede pasar sus propios parámetros:
  - `model`: Diferente modelo por sesión/run
  - `temperature`: Diferente creatividad por contexto
  - `max_tokens`: Límites específicos si es necesario
- **No hay limitación real:** La diferencia entre apps está en los parámetros, no en el cliente

## Uso por App

### Documents App
```python
from apps.document.utils.client_openia import embed_text

# Crea embeddings para chunks de documentos
embedding = embed_text(chunk_text)
```
- **Propósito:** Vectorización de contenido para RAG
- **Modelo:** `text-embedding-3-small` (fijo)
- **Frecuencia:** Alta (cada chunk procesado)

### Chat App
```python
from apps.document.utils.client_openia import generate_chat_completion

# Respuestas conversacionales con contexto RAG
response, usage = generate_chat_completion(
    messages=messages,
    model=session.model,  # Configurable por sesión
    temperature=session.temperature,  # Configurable por sesión
)
```
- **Propósito:** Conversación con contexto de documentos
- **Modelo:** Configurable (default: `gpt-4o-mini`)
- **Temperature:** Configurable (default: 0.1)

### Evaluations App
```python
from apps.document.utils.client_openia import generate_chat_completion

# Evaluaciones estructuradas de métricas
response, usage = generate_chat_completion(
    messages=messages,
    model=run.model,  # Configurable por run
    temperature=run.temperature,  # Configurable por run
)
```
- **Propósito:** Evaluación estructurada de KPIs/pilares
- **Modelo:** Configurable (default: `gpt-4o-mini`)
- **Temperature:** Configurable (default: 0.1)

## Alternativas Consideradas

### ❌ Clientes Separados por App

**Por qué NO:**
- Misma API key en todos → no hay beneficio de seguridad
- Múltiples conexiones HTTP → ineficiente
- Duplicación de código → más mantenimiento
- La configuración ya se pasa como parámetros → no se necesita separación

**Cuándo SÍ sería útil:**
- Si necesitaras diferentes API keys por app
- Si necesitaras timeouts/retries muy diferentes
- Si una app necesitara configuración especial que afectara a otras

### ✅ Servicio Centralizado (Implementado)

**Ventajas:**
- Cliente compartido eficiente
- Configuración flexible por llamada
- Fácil de extender (agregar parámetros como `max_tokens`, `timeout`)
- Mantiene simplicidad

## Extensibilidad Futura

Si en el futuro necesitas:
- **Diferentes timeouts por app:** Agrega parámetro `timeout` (ya implementado)
- **Diferentes retry policies:** Puedes crear wrappers específicos por app
- **Rate limiting por app:** Puedes agregar middleware de rate limiting
- **Múltiples API keys:** Puedes extender `get_openai_client()` para aceptar `api_key` opcional

**Sin cambiar la arquitectura base**, solo extendiendo la funcionalidad.

## Guía Completa de Personalización y Extensión

### 1. Acceso Directo al Cliente

Si necesitas usar funcionalidades de OpenAI que no están expuestas en las funciones wrapper, puedes acceder directamente al cliente:

```python
from apps.document.utils.client_openia import get_openai_client

# Obtener el cliente compartido
client = get_openai_client()

# Usar cualquier método de la API de OpenAI
response = client.audio.speech.create(
    model="tts-1",
    voice="alloy",
    input="Hello, world!"
)

# O usar otras APIs disponibles
images = client.images.generate(
    model="dall-e-3",
    prompt="A futuristic city",
    size="1024x1024",
    quality="standard",
    n=1,
)
```

**Ventaja:** Acceso completo a todas las capacidades de OpenAI sin duplicar la inicialización del cliente.

---

### 2. Crear Funciones Wrapper Personalizadas

Puedes crear funciones wrapper específicas para tus necesidades sin modificar el código base:

#### Ejemplo 1: Wrapper para Generación de Imágenes

```python
# En tu app (ej: apps/content/utils/openai_extensions.py)
from typing import List
from apps.document.utils.client_openia import get_openai_client

def generate_image(
    prompt: str,
    model: str = "dall-e-3",
    size: str = "1024x1024",
    quality: str = "standard",
    n: int = 1,
) -> List[str]:
    """
    Genera imágenes usando DALL-E.
    
    Args:
        prompt: Descripción de la imagen
        model: Modelo a usar (dall-e-2 o dall-e-3)
        size: Tamaño de la imagen
        quality: Calidad (standard o hd)
        n: Número de imágenes
        
    Returns:
        List[str]: URLs de las imágenes generadas
    """
    client = get_openai_client()
    response = client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        quality=quality,
        n=n,
    )
    return [image.url for image in response.data]
```

#### Ejemplo 2: Wrapper para Transcripción de Audio

```python
# En tu app
from apps.document.utils.client_openia import get_openai_client

def transcribe_audio(
    audio_file_path: str,
    model: str = "whisper-1",
    language: str | None = None,
    prompt: str | None = None,
) -> str:
    """
    Transcribe audio a texto usando Whisper.
    
    Args:
        audio_file_path: Ruta al archivo de audio
        model: Modelo Whisper a usar
        language: Código de idioma (opcional, ej: "es", "en")
        prompt: Contexto opcional para mejorar la transcripción
        
    Returns:
        str: Texto transcrito
    """
    client = get_openai_client()
    
    with open(audio_file_path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model=model,
            file=audio_file,
            language=language,
            prompt=prompt,
        )
    return transcript.text
```

#### Ejemplo 3: Wrapper con Retry Logic Personalizado

```python
# En tu app
import time
from typing import Callable, TypeVar
from apps.document.utils.client_openia import get_openai_client

T = TypeVar('T')

def with_retry(
    func: Callable[[], T],
    max_retries: int = 3,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,),
) -> T:
    """
    Ejecuta una función con retry automático y backoff exponencial.
    
    Args:
        func: Función a ejecutar
        max_retries: Número máximo de reintentos
        backoff_factor: Factor de espera entre reintentos
        exceptions: Excepciones que deben triggerar retry
        
    Returns:
        Resultado de la función
    """
    for attempt in range(max_retries):
        try:
            return func()
        except exceptions as e:
            if attempt == max_retries - 1:
                raise
            wait_time = backoff_factor ** attempt
            time.sleep(wait_time)
    raise RuntimeError("Should not reach here")

# Uso:
def generate_with_retry(messages, model, temperature):
    def _call():
        client = get_openai_client()
        return client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
    return with_retry(_call, max_retries=3)
```

---

### 3. Extender Funciones Existentes

Puedes crear versiones extendidas de las funciones existentes con lógica adicional:

#### Ejemplo: Chat Completion con Validación de Respuesta

```python
# En tu app
import json
from apps.document.utils.client_openia import generate_chat_completion

def generate_structured_response(
    messages: List[dict],
    expected_format: str = "json",
    model: str | None = None,
    temperature: float = 0.1,
) -> dict:
    """
    Genera una respuesta y valida que sea JSON válido.
    
    Args:
        messages: Mensajes del chat
        expected_format: Formato esperado ("json", "text")
        model: Modelo a usar
        temperature: Temperature
        
    Returns:
        dict: Respuesta parseada y validada
        
    Raises:
        ValueError: Si la respuesta no es válida
    """
    response_text, usage = generate_chat_completion(
        messages=messages,
        model=model,
        temperature=temperature,
    )
    
    if expected_format == "json":
        try:
            parsed = json.loads(response_text)
            return {
                "data": parsed,
                "raw": response_text,
                "usage": usage,
            }
        except json.JSONDecodeError:
            raise ValueError(f"Response is not valid JSON: {response_text}")
    
    return {
        "data": response_text,
        "usage": usage,
    }
```

---

### 4. Crear Clases de Servicio Especializadas

Para casos más complejos, puedes crear clases que encapsulen lógica específica:

#### Ejemplo: Servicio de Análisis de Documentos

```python
# En tu app (ej: apps/analytics/services/document_analyzer.py)
from typing import List, Dict
from apps.document.utils.client_openia import get_openai_client, embed_text

class DocumentAnalyzer:
    """
    Servicio especializado para análisis de documentos usando OpenAI.
    """
    
    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.1):
        self.client = get_openai_client()
        self.model = model
        self.temperature = temperature
    
    def summarize(self, text: str, max_length: int = 200) -> str:
        """
        Genera un resumen del texto.
        """
        messages = [
            {
                "role": "system",
                "content": f"Eres un experto en resumir documentos. Genera resúmenes concisos de máximo {max_length} palabras."
            },
            {
                "role": "user",
                "content": f"Resume el siguiente texto:\n\n{text}"
            }
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
            max_tokens=max_length * 2,  # Aproximadamente 2 tokens por palabra
        )
        return response
    
    def extract_keywords(self, text: str, count: int = 10) -> List[str]:
        """
        Extrae palabras clave del texto.
        """
        messages = [
            {
                "role": "system",
                "content": "Eres un experto en extraer palabras clave. Devuelve solo una lista de palabras clave, una por línea."
            },
            {
                "role": "user",
                "content": f"Extrae las {count} palabras clave más importantes del siguiente texto:\n\n{text}"
            }
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model=self.model,
            temperature=0.3,  # Más determinístico para keywords
        )
        
        keywords = [kw.strip() for kw in response.split("\n") if kw.strip()]
        return keywords[:count]
    
    def analyze_sentiment(self, text: str) -> Dict[str, float]:
        """
        Analiza el sentimiento del texto.
        """
        messages = [
            {
                "role": "system",
                "content": "Eres un analista de sentimientos. Responde solo con un JSON con las claves: positive, neutral, negative, cada una con un valor entre 0 y 1."
            },
            {
                "role": "user",
                "content": f"Analiza el sentimiento del siguiente texto:\n\n{text}"
            }
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model=self.model,
            temperature=0.1,
        )
        
        import json
        return json.loads(response)
    
    def compare_documents(self, doc1: str, doc2: str) -> str:
        """
        Compara dos documentos y genera un análisis.
        """
        messages = [
            {
                "role": "system",
                "content": "Eres un experto en análisis comparativo de documentos. Genera un análisis detallado de las similitudes y diferencias."
            },
            {
                "role": "user",
                "content": f"Compara estos dos documentos:\n\nDocumento 1:\n{doc1}\n\nDocumento 2:\n{doc2}"
            }
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model=self.model,
            temperature=self.temperature,
        )
        return response

# Uso:
analyzer = DocumentAnalyzer(model="gpt-4", temperature=0.2)
summary = analyzer.summarize(long_text)
keywords = analyzer.extract_keywords(long_text, count=15)
sentiment = analyzer.analyze_sentiment(review_text)
```

---

### 5. Agregar Nuevos Parámetros a Funciones Existentes

Si necesitas agregar parámetros a las funciones existentes, puedes hacerlo de forma no invasiva:

#### Ejemplo: Agregar Soporte para Stream

```python
# Extensión en tu app
from apps.document.utils.client_openia import get_openai_client

def generate_chat_completion_stream(
    messages: List[dict],
    *,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int | None = None,
):
    """
    Versión streaming de generate_chat_completion.
    Genera tokens incrementalmente.
    
    Yields:
        str: Tokens de la respuesta conforme se generan
    """
    client = get_openai_client()
    
    request_params = {
        "model": model or MODEL_COMPLETION,
        "temperature": temperature,
        "messages": messages,
        "stream": True,
    }
    
    if max_tokens is not None:
        request_params["max_tokens"] = max_tokens
    
    stream = client.chat.completions.create(**request_params)
    
    for chunk in stream:
        if chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content

# Uso:
for token in generate_chat_completion_stream(messages, model="gpt-4"):
    print(token, end="", flush=True)
```

---

### 6. Implementar Middleware/Decorators

Puedes crear decorators para agregar funcionalidad transversal:

#### Ejemplo: Decorator para Logging y Métricas

```python
# En tu app
import logging
import time
from functools import wraps
from typing import Callable, Any

logger = logging.getLogger(__name__)

def log_openai_call(func: Callable) -> Callable:
    """
    Decorator que loggea llamadas a OpenAI con métricas.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        model = kwargs.get("model", "default")
        
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            
            # Extraer usage si está disponible
            if isinstance(result, tuple) and len(result) == 2:
                response, usage = result
                logger.info(
                    f"OpenAI call successful: {func.__name__} | "
                    f"Model: {model} | Duration: {duration:.2f}s | "
                    f"Tokens: {usage.get('total_tokens', 'N/A')}"
                )
            else:
                logger.info(
                    f"OpenAI call successful: {func.__name__} | "
                    f"Model: {model} | Duration: {duration:.2f}s"
                )
            
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(
                f"OpenAI call failed: {func.__name__} | "
                f"Model: {model} | Duration: {duration:.2f}s | "
                f"Error: {str(e)}"
            )
            raise
    
    return wrapper

# Uso:
@log_openai_call
def my_custom_completion(messages, model, temperature):
    from apps.document.utils.client_openia import generate_chat_completion
    return generate_chat_completion(messages, model=model, temperature=temperature)
```

#### Ejemplo: Decorator para Rate Limiting

```python
# En tu app
import time
from collections import defaultdict
from functools import wraps
from typing import Callable

class RateLimiter:
    """Rate limiter simple para llamadas a OpenAI."""
    
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = defaultdict(list)
    
    def __call__(self, func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = func.__name__
            now = time.time()
            
            # Limpiar llamadas antiguas
            self.calls[key] = [
                call_time for call_time in self.calls[key]
                if now - call_time < self.time_window
            ]
            
            # Verificar límite
            if len(self.calls[key]) >= self.max_calls:
                sleep_time = self.time_window - (now - self.calls[key][0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                    # Limpiar después de esperar
                    self.calls[key] = []
            
            # Registrar llamada
            self.calls[key].append(time.time())
            
            return func(*args, **kwargs)
        
        return wrapper

# Uso:
rate_limiter = RateLimiter(max_calls=60, time_window=60.0)  # 60 llamadas por minuto

@rate_limiter
def rate_limited_completion(messages, model, temperature):
    from apps.document.utils.client_openia import generate_chat_completion
    return generate_chat_completion(messages, model=model, temperature=temperature)
```

---

### 7. Configuración Avanzada del Cliente

Si necesitas configurar el cliente con opciones avanzadas, puedes extender `get_openai_client()`:

#### Ejemplo: Cliente con Configuración Personalizada

```python
# En tu app o en una extensión de client_openia.py
from apps.document.utils.client_openia import get_openai_client
from openai import OpenAI

def get_custom_openai_client(
    timeout: float = 60.0,
    max_retries: int = 3,
    api_key: str | None = None,
) -> OpenAI:
    """
    Obtiene un cliente OpenAI con configuración personalizada.
    
    Nota: Esto crea un nuevo cliente, no reutiliza el compartido.
    Úsalo solo si necesitas configuración muy específica.
    """
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY not configured")
    
    return OpenAI(
        api_key=key,
        timeout=timeout,
        max_retries=max_retries,
    )

# O modificar el cliente compartido (si realmente lo necesitas):
def configure_shared_client():
    """
    Configura el cliente compartido con opciones avanzadas.
    Úsalo con cuidado, afecta a todas las apps.
    """
    from apps.document.utils.client_openia import get_openai_client
    
    client = get_openai_client()
    # El cliente de OpenAI ya viene con configuración razonable por defecto
    # Pero puedes ajustar timeouts, etc. si es necesario
    return client
```

---

### 8. Patrones de Uso Avanzados

#### Patrón: Chain of Prompts

```python
# En tu app
from apps.document.utils.client_openia import generate_chat_completion

def process_document_chain(text: str) -> dict:
    """
    Procesa un documento en múltiples pasos encadenados.
    """
    # Paso 1: Resumen
    summary, _ = generate_chat_completion(
        messages=[
            {"role": "system", "content": "Genera un resumen conciso."},
            {"role": "user", "content": f"Resume: {text}"}
        ],
        temperature=0.3,
    )
    
    # Paso 2: Análisis basado en el resumen
    analysis, _ = generate_chat_completion(
        messages=[
            {"role": "system", "content": "Analiza el contenido."},
            {"role": "user", "content": f"Analiza este resumen: {summary}"}
        ],
        temperature=0.5,
    )
    
    # Paso 3: Recomendaciones
    recommendations, _ = generate_chat_completion(
        messages=[
            {"role": "system", "content": "Genera recomendaciones prácticas."},
            {"role": "user", "content": f"Basado en: {analysis}\n\nGenera recomendaciones."}
        ],
        temperature=0.7,
    )
    
    return {
        "summary": summary,
        "analysis": analysis,
        "recommendations": recommendations,
    }
```

#### Patrón: Parallel Processing

```python
# En tu app
from concurrent.futures import ThreadPoolExecutor
from apps.document.utils.client_openia import generate_chat_completion

def process_multiple_documents_parallel(
    documents: List[str],
    prompt_template: str,
    max_workers: int = 3,
) -> List[str]:
    """
    Procesa múltiples documentos en paralelo.
    """
    def process_one(doc: str) -> str:
        messages = [
            {"role": "system", "content": "Procesa el documento."},
            {"role": "user", "content": prompt_template.format(document=doc)}
        ]
        response, _ = generate_chat_completion(messages, temperature=0.3)
        return response
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(process_one, documents))
    
    return results
```

---

### 9. Mejores Prácticas

#### ✅ DO (Hacer)

1. **Usa el cliente compartido cuando sea posible:**
   ```python
   # ✅ Correcto
   from apps.document.utils.client_openia import get_openai_client
   client = get_openai_client()
   ```

2. **Pasa parámetros por llamada:**
   ```python
   # ✅ Correcto - flexibilidad sin duplicar código
   generate_chat_completion(messages, model="gpt-4", temperature=0.7)
   ```

3. **Crea wrappers específicos para casos de uso:**
   ```python
   # ✅ Correcto - encapsula lógica específica
   def analyze_sentiment(text: str) -> dict:
       # Lógica específica aquí
   ```

4. **Maneja errores apropiadamente:**
   ```python
   # ✅ Correcto
   try:
       response, usage = generate_chat_completion(messages)
   except ValueError as e:
       logger.error(f"OpenAI error: {e}")
       # Manejo de error
   ```

#### ❌ DON'T (No hacer)

1. **No crees múltiples clientes innecesariamente:**
   ```python
   # ❌ Incorrecto - duplica conexiones
   client1 = OpenAI(api_key=key)
   client2 = OpenAI(api_key=key)
   ```

2. **No modifiques el cliente compartido sin necesidad:**
   ```python
   # ❌ Evitar - afecta a todas las apps
   client = get_openai_client()
   client.timeout = 999  # Afecta a todo
   ```

3. **No hardcodees configuración:**
   ```python
   # ❌ Incorrecto
   model = "gpt-4"  # Hardcoded
   
   # ✅ Correcto
   model = os.environ.get("MY_APP_MODEL", "gpt-4o-mini")
   ```

---

### 10. Testing y Mocking

Para testing, puedes mockear las funciones:

```python
# En tus tests
from unittest.mock import patch, MagicMock
from apps.document.utils.client_openia import generate_chat_completion

@patch('apps.document.utils.client_openia.generate_chat_completion')
def test_my_feature(mock_completion):
    # Configurar mock
    mock_completion.return_value = (
        "Mocked response",
        {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}
    )
    
    # Tu código que usa generate_chat_completion
    result = my_function_that_uses_openai()
    
    # Verificar
    assert result == expected_value
    mock_completion.assert_called_once()
```

---

## Conclusión

El enfoque de **cliente compartido con configuración flexible** es el óptimo porque:
1. ✅ Maximiza eficiencia (una conexión, reutilizada)
2. ✅ Mantiene simplicidad (un solo lugar de configuración)
3. ✅ Permite flexibilidad (parámetros por llamada)
4. ✅ Es fácil de extender (sin refactor mayor)

La diferencia entre apps está en **cómo usan** el servicio (parámetros), no en **qué servicio** usan (mismo cliente).

### Próximos Pasos para Personalización

1. **Identifica tus necesidades específicas:** ¿Qué funcionalidades de OpenAI necesitas?
2. **Crea wrappers en tu app:** No modifiques `client_openia.py` directamente
3. **Usa el cliente compartido:** Accede vía `get_openai_client()` cuando necesites APIs no expuestas
4. **Documenta tus extensiones:** Crea documentación específica para tus casos de uso
5. **Testea tus extensiones:** Asegúrate de mockear correctamente en tests

---

## 11. Casos de Uso Reales y Ejemplos Prácticos

### Caso 1: Sistema de Resúmenes Automáticos

```python
# apps/content/services/summarizer.py
from apps.document.utils.client_openia import generate_chat_completion
from typing import List

class AutoSummarizer:
    """Genera resúmenes automáticos de documentos."""
    
    def __init__(self, style: str = "executive"):
        self.style = style
        self.style_prompts = {
            "executive": "Genera un resumen ejecutivo conciso (2-3 párrafos).",
            "detailed": "Genera un resumen detallado con puntos clave.",
            "bullet": "Genera un resumen en formato de viñetas.",
        }
    
    def summarize(self, text: str, max_words: int = 150) -> str:
        """Genera resumen según el estilo configurado."""
        system_prompt = self.style_prompts.get(
            self.style,
            "Genera un resumen del texto."
        )
        
        user_prompt = f"""
        {system_prompt}
        Máximo {max_words} palabras.
        
        Texto a resumir:
        {text}
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response, usage = generate_chat_completion(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.3,
            max_tokens=max_words * 2,  # Aprox 2 tokens por palabra
        )
        
        return response

# Uso:
summarizer = AutoSummarizer(style="executive")
summary = summarizer.summarize(long_document, max_words=200)
```

### Caso 2: Traducción Multi-idioma

```python
# apps/content/services/translator.py
from apps.document.utils.client_openia import generate_chat_completion

class DocumentTranslator:
    """Traduce documentos manteniendo formato y contexto."""
    
    SUPPORTED_LANGUAGES = {
        "es": "español",
        "en": "inglés",
        "fr": "francés",
        "de": "alemán",
        "pt": "portugués",
    }
    
    def translate(
        self,
        text: str,
        target_language: str,
        source_language: str | None = None,
        preserve_formatting: bool = True,
    ) -> str:
        """
        Traduce texto a otro idioma.
        
        Args:
            text: Texto a traducir
            target_language: Idioma destino (código ISO)
            source_language: Idioma origen (opcional, auto-detecta)
            preserve_formatting: Mantener formato original
        """
        target = self.SUPPORTED_LANGUAGES.get(target_language, target_language)
        source = f" desde {self.SUPPORTED_LANGUAGES[source_language]}" if source_language else ""
        
        system_prompt = f"""
        Eres un traductor profesional. Traduce el texto{source} al {target}.
        {"Mantén el formato, estructura y estilo del texto original." if preserve_formatting else ""}
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.2,  # Bajo para traducciones consistentes
        )
        
        return response

# Uso:
translator = DocumentTranslator()
translated = translator.translate(
    "Hello, world!",
    target_language="es",
    source_language="en"
)
```

### Caso 3: Extracción de Entidades y Datos Estructurados

```python
# apps/analytics/services/entity_extractor.py
import json
from apps.document.utils.client_openia import generate_chat_completion
from typing import Dict, List

class EntityExtractor:
    """Extrae entidades y datos estructurados de texto."""
    
    def extract_entities(
        self,
        text: str,
        entity_types: List[str] = None,
    ) -> Dict:
        """
        Extrae entidades nombradas del texto.
        
        Args:
            text: Texto del cual extraer entidades
            entity_types: Tipos de entidades a extraer (personas, organizaciones, fechas, etc.)
        """
        entity_types = entity_types or ["personas", "organizaciones", "fechas", "lugares"]
        
        system_prompt = """
        Eres un experto en extracción de entidades nombradas.
        Extrae todas las entidades del texto y devuélvelas en formato JSON.
        Estructura: {"personas": [], "organizaciones": [], "fechas": [], "lugares": []}
        """
        
        user_prompt = f"""
        Extrae las siguientes entidades del texto: {', '.join(entity_types)}
        
        Texto:
        {text}
        """
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.1,  # Muy determinístico para extracción
        )
        
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # Fallback: intentar extraer JSON del texto
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            raise ValueError(f"Could not parse JSON from response: {response}")

# Uso:
extractor = EntityExtractor()
entities = extractor.extract_entities(
    "Juan Pérez de la empresa Ecofilia visitó Madrid el 15 de marzo de 2024.",
    entity_types=["personas", "organizaciones", "lugares", "fechas"]
)
# Resultado: {"personas": ["Juan Pérez"], "organizaciones": ["Ecofilia"], ...}
```

### Caso 4: Generación de Contenido con Plantillas

```python
# apps/content/services/content_generator.py
from apps.document.utils.client_openia import generate_chat_completion
from typing import Dict

class ContentGenerator:
    """Genera contenido basado en plantillas y contexto."""
    
    TEMPLATES = {
        "email": """
        Genera un email profesional con:
        - Asunto claro y conciso
        - Saludo apropiado
        - Cuerpo del mensaje
        - Cierre profesional
        
        Contexto: {context}
        Objetivo: {objective}
        """,
        "report": """
        Genera un reporte estructurado con:
        - Introducción
        - Hallazgos principales
        - Conclusiones
        - Recomendaciones
        
        Datos: {data}
        """,
        "proposal": """
        Genera una propuesta con:
        - Resumen ejecutivo
        - Problema identificado
        - Solución propuesta
        - Beneficios esperados
        - Próximos pasos
        
        Contexto: {context}
        """
    }
    
    def generate(
        self,
        template_type: str,
        context: Dict,
        tone: str = "professional",
    ) -> str:
        """
        Genera contenido usando una plantilla.
        
        Args:
            template_type: Tipo de plantilla (email, report, proposal)
            context: Diccionario con datos para la plantilla
            tone: Tono del contenido (professional, casual, formal)
        """
        template = self.TEMPLATES.get(template_type)
        if not template:
            raise ValueError(f"Template '{template_type}' not found")
        
        system_prompt = f"""
        Eres un experto en redacción de contenido {tone}.
        Genera contenido de alta calidad basado en la plantilla proporcionada.
        """
        
        user_prompt = template.format(**context)
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        response, _ = generate_chat_completion(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.7,  # Más creativo para generación de contenido
        )
        
        return response

# Uso:
generator = ContentGenerator()
email = generator.generate(
    template_type="email",
    context={
        "context": "Reunión de seguimiento del proyecto",
        "objective": "Confirmar próxima reunión"
    },
    tone="professional"
)
```

### Caso 5: Análisis Comparativo con Embeddings

```python
# apps/analytics/services/document_comparator.py
from apps.document.utils.client_openia import generate_chat_completion, embed_text
import numpy as np
from typing import List, Tuple

class DocumentComparator:
    """Compara documentos usando embeddings y análisis de contenido."""
    
    def compare_semantic_similarity(
        self,
        doc1: str,
        doc2: str,
    ) -> Tuple[float, str]:
        """
        Compara dos documentos usando embeddings y genera análisis.
        
        Returns:
            Tuple[float, str]: (similarity_score, analysis_text)
        """
        # Calcular embeddings
        emb1 = np.array(embed_text(doc1))
        emb2 = np.array(embed_text(doc2))
        
        # Calcular similitud coseno
        similarity = np.dot(emb1, emb2) / (np.linalg.norm(emb1) * np.linalg.norm(emb2))
        
        # Generar análisis textual
        messages = [
            {
                "role": "system",
                "content": "Eres un experto en análisis comparativo de documentos."
            },
            {
                "role": "user",
                "content": f"""
                Compara estos dos documentos y genera un análisis detallado:
                - Similitudes principales
                - Diferencias clave
                - Áreas de complementariedad
                
                Documento 1:
                {doc1[:1000]}...
                
                Documento 2:
                {doc2[:1000]}...
                """
            }
        ]
        
        analysis, _ = generate_chat_completion(
            messages=messages,
            model="gpt-4o-mini",
            temperature=0.3,
        )
        
        return float(similarity), analysis

# Uso:
comparator = DocumentComparator()
similarity, analysis = comparator.compare_semantic_similarity(doc1, doc2)
print(f"Similitud: {similarity:.2%}")
print(f"Análisis: {analysis}")
```

---

## 12. Troubleshooting y Solución de Problemas

### Problema: Rate Limits

**Síntoma:** `RateLimitError` o `429 Too Many Requests`

**Solución:**
```python
# Implementa rate limiting
from apps.content.utils.rate_limiter import RateLimiter

rate_limiter = RateLimiter(max_calls=60, time_window=60.0)

@rate_limiter
def my_openai_call():
    # Tu código aquí
    pass
```

### Problema: Timeouts

**Síntoma:** `TimeoutError` o respuestas muy lentas

**Solución:**
```python
# Usa el parámetro timeout
response, usage = generate_chat_completion(
    messages=messages,
    timeout=30.0,  # 30 segundos
)
```

### Problema: Respuestas Inconsistentes

**Síntoma:** Mismo input produce diferentes outputs

**Solución:**
```python
# Usa temperature más baja para consistencia
response, usage = generate_chat_completion(
    messages=messages,
    temperature=0.1,  # Más determinístico
)
```

### Problema: Costos Altos

**Síntoma:** Uso excesivo de tokens

**Solución:**
```python
# Limita tokens de salida
response, usage = generate_chat_completion(
    messages=messages,
    max_tokens=500,  # Limita la longitud de la respuesta
)

# Monitorea usage
print(f"Tokens usados: {usage['total_tokens']}")
```

---

## Recursos Adicionales

- [OpenAI Python SDK Documentation](https://github.com/openai/openai-python)
- [OpenAI API Reference](https://platform.openai.com/docs/api-reference)
- [Best Practices for OpenAI API](https://platform.openai.com/docs/guides/best-practices)
- [OpenAI Cookbook](https://cookbook.openai.com/) - Ejemplos y recetas
- [Token Usage Guide](https://platform.openai.com/docs/guides/rate-limits) - Gestión de límites

