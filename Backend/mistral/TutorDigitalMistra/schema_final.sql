-- ============================================================================
-- SCHEMA DEFINITIVO - Tutor Virtual LMS con RAG Híbrido
-- PostgreSQL 16+ con pgvector
-- ============================================================================

-- 1. EXTENSIONES
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- 2. FUNCIONES AUXILIARES
CREATE OR REPLACE FUNCTION update_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.fecha_actualizacion = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- MÓDULO: LICENCIAS Y USUARIOS
-- ============================================================================

CREATE TABLE licencias (
    id SERIAL PRIMARY KEY,
    cliente VARCHAR(255) NOT NULL,
    max_alumnos INTEGER NOT NULL,
    fecha_inicio TIMESTAMP NOT NULL,
    fecha_fin TIMESTAMP NOT NULL,
    activa BOOLEAN DEFAULT TRUE
);

CREATE TABLE usuarios (
    id SERIAL PRIMARY KEY,
    licencia_id INTEGER NOT NULL REFERENCES licencias(id),
    nombre VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    rol VARCHAR(50) NOT NULL CHECK (rol IN ('alumno', 'admin', 'profesor')),
    activo BOOLEAN DEFAULT TRUE,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_usuarios_email ON usuarios(email);
CREATE INDEX idx_usuarios_licencia ON usuarios(licencia_id);

CREATE TRIGGER update_usuarios_time BEFORE UPDATE ON usuarios 
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

-- ============================================================================
-- MÓDULO: CONTENIDOS (LIBROS Y RAG HÍBRIDO)
-- ============================================================================

CREATE TABLE libros (
    id SERIAL PRIMARY KEY,
    titulo VARCHAR(255) NOT NULL,
    autor VARCHAR(255),
    descripcion TEXT,
    pdf_path VARCHAR(500),
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    activo BOOLEAN DEFAULT TRUE
);

CREATE TABLE temario (
    id SERIAL PRIMARY KEY,
    libro_id INTEGER REFERENCES libros(id) ON DELETE CASCADE,
    parent_id INTEGER REFERENCES temario(id),
    nombre VARCHAR(255) NOT NULL,
    descripcion TEXT,
    nivel INTEGER NOT NULL DEFAULT 1,
    orden INTEGER NOT NULL,
    pagina_inicio INTEGER,
    activo BOOLEAN DEFAULT TRUE
);

CREATE INDEX idx_temario_parent ON temario(parent_id);
CREATE INDEX idx_temario_libro ON temario(libro_id);

-- TABLA CORE: Base de Conocimiento con Búsqueda Híbrida
CREATE TABLE base_conocimiento (
    id BIGSERIAL PRIMARY KEY,
    temario_id INTEGER NOT NULL REFERENCES temario(id) ON DELETE CASCADE,
    
    -- Contenido
    contenido TEXT NOT NULL,
    tipo_contenido VARCHAR(50) DEFAULT 'texto',
    
    -- Referencias
    ref_fuente VARCHAR(100),
    pagina INTEGER,
    orden_aparicion INTEGER DEFAULT 0,

    -- Lista Enlazada para lectura secuencial
    chunk_anterior_id BIGINT REFERENCES base_conocimiento(id),
    chunk_siguiente_id BIGINT REFERENCES base_conocimiento(id),

    -- Motores de Búsqueda
    embedding VECTOR(1536),
    busqueda_texto TSVECTOR,
    
    metadatos JSONB DEFAULT '{}'::jsonb
);

-- Índices optimizados
CREATE INDEX idx_base_conocimiento_embedding ON base_conocimiento USING hnsw (embedding vector_cosine_ops);
CREATE INDEX idx_base_conocimiento_fts ON base_conocimiento USING GIN (busqueda_texto);
CREATE INDEX idx_base_conocimiento_temario ON base_conocimiento(temario_id);
CREATE INDEX idx_base_conocimiento_secuencia ON base_conocimiento(chunk_siguiente_id);
CREATE INDEX idx_base_conocimiento_metadatos ON base_conocimiento USING GIN(metadatos);

-- Trigger para actualizar búsqueda de texto automáticamente
CREATE OR REPLACE FUNCTION tsvector_update_trigger()
RETURNS TRIGGER AS $$
BEGIN
  NEW.busqueda_texto := setweight(to_tsvector('spanish', unaccent(COALESCE(NEW.contenido, ''))), 'A');
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tsvectorupdate BEFORE INSERT OR UPDATE
ON base_conocimiento FOR EACH ROW EXECUTE FUNCTION tsvector_update_trigger();

CREATE TABLE preguntas_comunes (
    id SERIAL PRIMARY KEY,
    temario_id INTEGER NOT NULL REFERENCES temario(id),
    pregunta TEXT NOT NULL,
    respuesta TEXT NOT NULL
);

-- ============================================================================
-- MÓDULO: EVALUACIONES
-- ============================================================================

CREATE TABLE tests (
    id SERIAL PRIMARY KEY,
    temario_id INTEGER NOT NULL REFERENCES temario(id),
    titulo VARCHAR(255) NOT NULL,
    contenido_examen JSONB NOT NULL,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE intentos_alumno (
    id SERIAL PRIMARY KEY,
    alumno_id INTEGER NOT NULL REFERENCES usuarios(id),
    test_id INTEGER NOT NULL REFERENCES tests(id),
    nota_final FLOAT NOT NULL,
    respuestas_alumno JSONB NOT NULL,
    fecha_realizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE assessments (
    id SERIAL PRIMARY KEY,
    temario_id INTEGER NOT NULL REFERENCES temario(id),
    titulo VARCHAR(255) NOT NULL,
    topic_metadata VARCHAR(255),
    total_preguntas INTEGER DEFAULT 0,
    generated_json_payload JSONB NOT NULL,
    temperatura FLOAT DEFAULT 0.7,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE test_scores (
    id SERIAL PRIMARY KEY,
    assessment_id INTEGER NOT NULL REFERENCES assessments(id),
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    score FLOAT DEFAULT 0.0,
    respuestas_alumno JSONB,
    ai_feedback_log TEXT,
    tiempo_segundos INTEGER,
    fecha_envio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- MÓDULO: CHAT Y CITAS
-- ============================================================================

CREATE TABLE sesiones_chat (
    id BIGSERIAL PRIMARY KEY,
    alumno_id INTEGER NOT NULL REFERENCES usuarios(id),
    temario_id INTEGER REFERENCES temario(id),
    titulo_resumen VARCHAR(255) NOT NULL,
    fecha_inicio TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE mensajes_chat (
    id BIGSERIAL PRIMARY KEY,
    sesion_id BIGINT NOT NULL REFERENCES sesiones_chat(id),
    rol VARCHAR(20) NOT NULL,
    texto TEXT NOT NULL,
    embedding VECTOR(1536),
    info_tecnica JSONB,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE chat_citas (
    id BIGSERIAL PRIMARY KEY,
    mensaje_id BIGINT NOT NULL REFERENCES mensajes_chat(id),
    base_conocimiento_id BIGINT NOT NULL REFERENCES base_conocimiento(id),
    score_similitud FLOAT
);

CREATE TABLE embedding_cache (
    text_hash VARCHAR(64) PRIMARY KEY,
    original_text TEXT NOT NULL,
    embedding VECTOR(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ============================================================================
-- MÓDULO: PROGRESO (Sin trigger automático)
-- ============================================================================

CREATE TABLE enrollments (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    libro_id INTEGER NOT NULL REFERENCES libros(id),
    licencia_id INTEGER REFERENCES licencias(id),
    fecha_matricula TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    estado VARCHAR(20) DEFAULT 'activo',
    progreso_global FLOAT DEFAULT 0.0,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_enrollments_usuario ON enrollments(usuario_id);
CREATE INDEX idx_enrollments_libro ON enrollments(libro_id);

CREATE TRIGGER update_enrollments_time BEFORE UPDATE ON enrollments 
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TABLE progreso_alumno (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    temario_id INTEGER NOT NULL REFERENCES temario(id),
    ultimo_contenido_visto_id BIGINT REFERENCES base_conocimiento(id),
    estado VARCHAR(20) DEFAULT 'en_progreso',
    nivel_comprension INTEGER DEFAULT 0 CHECK (nivel_comprension BETWEEN 0 AND 5),
    conceptos_debiles JSONB DEFAULT '[]'::jsonb,
    fecha_actualizacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TRIGGER update_progreso_time BEFORE UPDATE ON progreso_alumno 
FOR EACH ROW EXECUTE FUNCTION update_timestamp();

CREATE TABLE ejercicios_codigo (
    id SERIAL PRIMARY KEY,
    base_conocimiento_id BIGINT NOT NULL REFERENCES base_conocimiento(id),
    solucion_esperada TEXT NOT NULL,
    pistas TEXT,
    dificultad INTEGER DEFAULT 1
);

-- ============================================================================
-- MÓDULO: TELEMETRÍA
-- ============================================================================

CREATE TABLE learning_events (
    id BIGSERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    action_type VARCHAR(100) NOT NULL,
    detalle TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE metricas_consumo (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER NOT NULL REFERENCES usuarios(id),
    servicio VARCHAR(100) NOT NULL,
    tokens_gastados INTEGER NOT NULL,
    coste FLOAT NOT NULL,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE logs_errores (
    id SERIAL PRIMARY KEY,
    origen VARCHAR(255) NOT NULL,
    nivel VARCHAR(50) NOT NULL,
    mensaje TEXT NOT NULL,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE configuracion (
    clave VARCHAR(100) PRIMARY KEY,
    valor VARCHAR(255) NOT NULL,
    descripcion VARCHAR(255)
);

-- ============================================================================
-- FUNCIONES SQL NATIVAS PARA RAG
-- ============================================================================

-- Búsqueda Híbrida (Vector 70% + Full-Text 30%)
CREATE OR REPLACE FUNCTION buscar_contenido_hibrido(
    query_text TEXT, 
    query_embedding VECTOR(1536), 
    match_threshold FLOAT DEFAULT 0.3, 
    match_count INT DEFAULT 5,
    libro_filter INT DEFAULT NULL
)
RETURNS TABLE (
    id BIGINT,
    contenido TEXT,
    pagina INT,
    temario_id INT,
    score FLOAT
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        bc.id,
        bc.contenido,
        bc.pagina,
        bc.temario_id,
        (
            (1 - (bc.embedding <=> query_embedding)) * 0.7 + 
            (ts_rank(bc.busqueda_texto, plainto_tsquery('spanish', query_text))) * 0.3
        )::FLOAT AS score
    FROM base_conocimiento bc
    LEFT JOIN temario t ON bc.temario_id = t.id
    WHERE (libro_filter IS NULL OR t.libro_id = libro_filter)
    AND (1 - (bc.embedding <=> query_embedding)) > match_threshold
    ORDER BY score DESC
    LIMIT match_count;
END;
$$ LANGUAGE plpgsql;

-- Lectura Secuencial (CTE Recursivo)
CREATE OR REPLACE FUNCTION leer_secuencialmente(
    start_chunk_id BIGINT, 
    cantidad_bloques INT DEFAULT 3
)
RETURNS TABLE (
    orden_lectura INT,
    chunk_id BIGINT,
    contenido TEXT,
    pagina INT
) AS $$
BEGIN
    RETURN QUERY
    WITH RECURSIVE cadena_lectura AS (
        SELECT 
            1 AS orden,
            bc.id, 
            bc.contenido, 
            bc.pagina, 
            bc.chunk_siguiente_id
        FROM base_conocimiento bc
        WHERE bc.id = start_chunk_id
        
        UNION ALL
        
        SELECT 
            cl.orden + 1,
            bc.id, 
            bc.contenido, 
            bc.pagina, 
            bc.chunk_siguiente_id
        FROM base_conocimiento bc
        JOIN cadena_lectura cl ON bc.id = cl.chunk_siguiente_id
        WHERE cl.orden < cantidad_bloques
    )
    SELECT orden, id, cadena_lectura.contenido, cadena_lectura.pagina 
    FROM cadena_lectura;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- DATOS SEED
-- ============================================================================

INSERT INTO licencias (cliente, max_alumnos, fecha_inicio, fecha_fin, activa)
VALUES ('Escuela Demo', 100, NOW(), NOW() + INTERVAL '1 year', TRUE);

INSERT INTO usuarios (licencia_id, nombre, email, password_hash, rol)
VALUES (1, 'Admin', 'admin@demo.com', 'hash_placeholder', 'admin');

INSERT INTO libros (titulo, autor, descripcion)
VALUES ('Python para todos', 'Raúl González Duque', 'Libro introductorio a Python');
