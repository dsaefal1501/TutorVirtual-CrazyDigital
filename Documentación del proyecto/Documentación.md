

---

# Tutor virtual

Esta es una documentación donde se abarca todos los temas relacionados con este, desde requisitos, funcionalidad hasta casos de usos.

## ÍNDICE DE CONTENIDOS

**1 - Sobre este proyecto**

* 1.1 - Control de versiones
* 1.2 - Licencia de uso

**2 - Objetivo y Requisitos del programa**


**2.2 - Requisitos**

* 2.2.1 - Funcionales
* 2.2.2 - No funcionales

**2.3 - Recursos**

* 2.3.1 - Software
* 2.3.2 - Hardware

**3 - Diseño de la solución software**

* 3.1 - Modelados
* 3.1.1 - Casos de uso
* 3.1.2 - Interacción
* 3.1.3 - Estado
* 3.1.4 - Actividad


* 3.2 - Prototipado gráfico
* 3.2.1 - Escritorio
* 3.2.2 - Tablets / Smartphones


* 3.3 - Base de datos
* 3.3.1 - Diseño Conceptual (ER)
* 3.3.2 - Diseño lógico (tablas normalizadas)



**4 - Implementación**

* 4.1 - Codificación
* 4.1.1 - Usabilidad
* 4.1.2 - Backend
* 4.1.3 - Frontend


* 4.2 - Pruebas

**5 - Documentación**

* 5.1 - Empaquetado / Distribución
* 5.2 - Instalación
* 5.3 - Manual de Usuario / Referencia

**6 - Conclusiones**

**7 - Bibliografía**

---

## 1 - Sobre este proyecto

### 1.1 - Control de versiones

Para el control de versiones se usará **GitHub**, utilizando diferentes ramas para no interferir con el desarrollo de otros compañeros. Cada *commit* deberá estar acompañado de una descripción donde se explique exactamente qué archivos se han modificado, qué funcionalidades se han agregado o quitado y qué bugs se han solucionado.

### 1.2 - Licencia de uso

## 2 -Objetivo y requisitos 
### 2.1 - Objetivo
El objetivo de este programa es mejorar la educación haciéndola mas interactiva con el usuario y ofreciendo estadísticas de las notas y progresión mediante la implementación de inteligencia artificial.

El programa trata de una inteligencia artificial especializada para el aprendizaje guiado en ese sector, con el que el alumno se puede comunicar mediante texto o mediante una conversación por voz, la IA se representa en un avatar 3D expresivo lo que ayuda a la inmersión del alumno, tanto las notas como la progresión puede ser supervisada por el instructor mediante la interfaz para instructores.

## 2.2 - Requisitos

### 2.2.1 - Funcionales
Estos requisitos definen las interacciones específicas y funciones que el sistema debe ejecutar para alumnos e instructores.

**Gestión de Usuarios y Accesos**

-   **RF-01 Autenticación Externa:** El sistema debe integrarse con el servidor externo designado para validar las credenciales (usuario y contraseña) e identificar el rol del usuario (Alumno o Instructor).
    
-   **RF-02 Perfil de Usuario:** El sistema debe recuperar y mostrar la información básica del usuario (nombre, ID) una vez validada la sesión.
    

**Interacción con el Tutor IA (Rol Alumno)**

-   **RF-03 Interfaz de Chat Multimodal:** El sistema debe permitir la entrada de consultas tanto por **texto** (teclado) como por **voz** (micrófono).
    
-   **RF-04 Procesamiento de Voz (STT/TTS):** El sistema debe convertir la voz del usuario a texto para procesarla (Speech-to-Text) y convertir la respuesta de la IA en audio audible (Text-to-Speech).
    
-   **RF-05 Representación de Avatar 3D:** El sistema debe renderizar un avatar 3D en la interfaz principal que reaccione visualmente durante la interacción.
    
-   **RF-06 Sincronización Labial (Lip-Sync):** El movimiento de los labios del avatar debe estar sincronizado automáticamente con la respuesta de audio generada por la IA.
    
-   **RF-07 Historial de Sesiones:** El alumno debe poder visualizar y acceder a un registro de sus conversaciones anteriores con el tutor.
    

**Gestión Académica y Supervisión (Rol Instructor)**

-   **RF-08 Registro de Progreso:** El sistema debe calcular y almacenar métricas de desempeño del alumno (temas completados, calificaciones de evaluaciones, tiempo de estudio).
    
-   **RF-09 Panel del Instructor (Dashboard):** El sistema debe proporcionar una interfaz exclusiva para instructores donde puedan buscar alumnos y visualizar sus estadísticas de progresión mediante gráficos.

- **RF-10 Gestión de alumnos**: El sistema debe dar opción al instructor para dar de alta a alumnos mediante el correo del alumno donde se le genera una contraseña aleatoria que sirve para el primer acceso luego será obligatorio cambiar la contraseña

**Gestión Administrativa y Comercial (Rol Vendedor/Admin)**

-   **RF-11 Gestión de Licencias y Suscripciones:** El sistema debe proporcionar un panel de administración que permita a los vendedores generar, asignar y revocar licencias de acceso para instituciones o usuarios individuales.
    
-   **RF-12 Control de Vigencia (Temporizador):** El sistema debe validar automáticamente la fecha de caducidad de la suscripción cada vez que un usuario intente iniciar sesión, denegando el acceso si el periodo contratado ha finalizado.
    
-   **RF-13 Límites de Usuarios (Cuotas):** El sistema debe permitir al vendedor configurar un límite máximo de alumnos activos por licencia (ej. "Plan Escuela: hasta 500 alumnos") y bloquear nuevos registros si se supera dicha cuota.
    
-   **RF-14 Estado del Servicio:** El vendedor debe tener la capacidad de suspender o reactivar manualmente el acceso a una cuenta o institución (por ejemplo, por falta de pago) mediante un interruptor de estado (Activo/Inactivo).
	
    **Mantenimiento Técnico y Administración del Sistema (Rol Administrador Informático)**

-   **RF-15 Configuración de Parámetros Globales:** El sistema debe ofrecer una interfaz técnica para configurar variables críticas sin necesidad de reiniciar el código, tales como:
    
    -   Endpoint (URL) del servidor de autenticación externo.
        
    -   API Keys del motor de Inteligencia Artificial.
        
    -   Umbrales de latencia máxima permitida.
        
-   **RF-16 Visualización de Logs y Errores:** El sistema debe registrar y permitir la consulta filtrada de logs técnicos (registros de eventos), detallando errores de conexión, fallos en la renderización del avatar o excepciones en la respuesta de la IA para facilitar la depuración (debugging).
    
-   **RF-17 Monitorización de Consumo de IA:** El sistema debe mostrar un reporte en tiempo real del uso de tokens o peticiones a la API de Inteligencia Artificial para controlar costes y prevenir saturaciones.
    
-   **RF-18 Gestión de Copias de Seguridad (Backups):** El sistema debe permitir al administrador ejecutar copias de seguridad manuales y programar copias automáticas de la base de datos local (donde se guarda el progreso y las estadísticas).
    
-   **RF-19 Reinicio de Servicios:** El sistema debe permitir reiniciar módulos específicos (ej. el módulo de voz o el conector con el servidor externo) desde el panel de administración en caso de bloqueo.

### 2.2.2 - No funcionales

**Rendimiento y Latencia**

-   **RNF-01 Latencia de Respuesta:** El tiempo transcurrido entre la consulta del usuario y el inicio de la respuesta del avatar (voz y animación) no debe exceder los **3 segundos** para mantener la naturalidad de la conversación.
    
-   **RNF-02 Fluidez Gráfica (FPS):** El renderizado del avatar 3D debe mantenerse estable a un mínimo de **30 cuadros por segundo (FPS)** en hardware estándar para evitar la fatiga visual.
    
-   **RNF-03 Calidad de Audio:** La síntesis de voz (TTS) debe ser clara, sin ruido estático y con una entonación natural, evitando voces excesivamente robóticas.
    

**Interoperabilidad y Seguridad**

-   **RNF-04 Comunicación Segura:** Toda la transferencia de datos (especialmente credenciales y voz) entre el cliente, el servidor externo de autenticación y el motor de IA debe realizarse sobre protocolo **HTTPS/WSS (WebSockets Secure)**.
    
-   **RNF-05 Dependencia de API:** El sistema debe ser capaz de gestionar errores de conexión con el servidor de autenticación externo sin bloquear la aplicación (tiempo de espera/timeout configurado a 5 segundos).
    

**Usabilidad**

-   **RNF-06 Accesibilidad:** La interfaz debe ser intuitiva, permitiendo iniciar una lección en no más de **3 clics** después del inicio de sesión.
    
-   **RNF-07 Feedback Visual:** El sistema debe indicar claramente cuando la IA está "pensando" o "escuchando" para que el usuario sepa el estado del sistema.

## 2.3 - Recursos

### 2.3.1 - Software
**Fronted** 

Unity para la parte de uso publico ya que se requiere una aplicación de escritorio para  

**Backend**
Se usa el framework fastapi debido a que es muy ligero y es el framework ideal para la ia

**Software gestor de datos**
PostgreSQL
### 2.3.2 - Hardware
**Servidor Azure**




## 3 - Diseño de la solución software

### 3.1 - Modelados


#### 3.1.1 - Casos de uso

Que acciones podra realizar cada rol en el programa, el grafico esta realizado en mermaid el código de este esta en al carpeta recursos
<img width="1185" height="859" alt="image" src="https://github.com/user-attachments/assets/5ffccd40-e2c8-42f1-ac21-d01297cfa386" />
#### 3.1.2 - Interacción

#### 3.1.3 - Estado

#### 3.1.4 - Actividad

### 3.2 - Prototipado gráfico

#### 3.2.1 - Escritorio

#### 3.2.2 - Tablets / Smartphones

### 3.3 - Base de datos

<img width="912" height="882" alt="image" src="https://github.com/user-attachments/assets/d48cc4e5-2ac9-4aad-ae86-a8a9c5a7045b" />


## 4 - Implementación

### 4.1 - Codificación

#### 4.1.1 - Usabilidad

#### 4.1.2 - Backend

#### 4.1.3 - Frontend

### 4.2 - Pruebas

## 5 - Documentación

### 5.1 - Empaquetado / Distribución

### 5.2 - Instalación

### 5.3 - Manual de Usuario / Referencia

## 6 - Conclusiones

## 7 - Bibliografía
