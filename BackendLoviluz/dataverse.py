"""
backend/app/services/dataverse.py
Servicio robusto para integración con Microsoft Dataverse
VERSIÓN MEJORADA v2.4: Código completo y seguro
"""

import requests
import logging
import os
import re
from typing import Dict, Optional, List, Any
from msal import ConfidentialClientApplication
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataverseClient:
    """
    Cliente para interactuar con Microsoft Dynamics 365 / Dataverse API
    """
    
    # ═══════════════════════════════════════════════════════════════
    # MAPEO DE IDs (✅ Correcto, no tocar)
    # ═══════════════════════════════════════════════════════════════
    ID_FIELD_MAPPING = {
        'task': 'activityid',           
        'tasks': 'activityid',          
        'appointment': 'activityid',
        'email': 'activityid',
        'phonecall': 'activityid',
        'contact': 'contactid',
        'contacts': 'contactid',
        'account': 'accountid',
        'accounts': 'accountid',
        'lead': 'leadid',
        'opportunity': 'opportunityid',
        'incident': 'incidentid',      
        'contract': 'contractid',
        'systemuser': 'systemuserid',
        'crazy_contrato': 'crazy_contratoid',
        'crazy_contratos': 'crazy_contratoid',
    }
    
    def __init__(self):
        """
        Inicializa el cliente con credenciales de Azure AD.
        
        REQUIERE las siguientes variables de entorno:
        - AZURE_TENANT_ID
        - AZURE_CLIENT_ID
        - AZURE_CLIENT_SECRET
        - DYNAMICS_BASE_URL
        
        Raises:
            ValueError: Si falta alguna variable de entorno requerida
        """
        
        # ═══════════════════════════════════════════════════════════════
        # CREDENCIALES (SOLO desde variables de entorno)
        # ═══════════════════════════════════════════════════════════════
        self.tenant_id = os.getenv('AZURE_TENANT_ID')
        self.client_id = os.getenv('AZURE_CLIENT_ID')
        self.client_secret = os.getenv('AZURE_CLIENT_SECRET')
        self.base_url = os.getenv('DYNAMICS_BASE_URL')
        
        # ═══════════════════════════════════════════════════════════════
        # VALIDACIÓN DE VARIABLES REQUERIDAS
        # ═══════════════════════════════════════════════════════════════
        missing_vars = []
        if not self.tenant_id:
            missing_vars.append('AZURE_TENANT_ID')
        if not self.client_id:
            missing_vars.append('AZURE_CLIENT_ID')
        if not self.client_secret:
            missing_vars.append('AZURE_CLIENT_SECRET')
        if not self.base_url:
            missing_vars.append('DYNAMICS_BASE_URL')
        
        if missing_vars:
            raise ValueError(
                f"❌ DATAVERSE CONFIG ERROR: Faltan las siguientes variables de entorno: "
                f"{', '.join(missing_vars)}. "
                f"Configúralas en .env o en las variables de entorno del sistema."
            )
        
        # Configuración MSAL
        self.authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        self.scope = [f"{self.base_url.split('/api')[0]}/.default"]
        
        self.app = ConfidentialClientApplication(
            self.client_id, 
            authority=self.authority, 
            client_credential=self.client_secret
        )
        
        # Caché de token
        self._token_cache = None
        self._token_expiry = None
        
        # Headers base
        self.headers = {
            'OData-MaxVersion': '4.0',
            'OData-Version': '4.0',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'Prefer': 'return=representation'
        }
        
        logger.info(f"✅ DataverseClient inicializado: {self.base_url}")
    
    def _get_access_token(self) -> str:
        """
        Obtiene token de acceso (con caché para mejor rendimiento)
        """
        # Si tenemos token válido en caché, usarlo
        if (self._token_cache and self._token_expiry and 
            datetime.now() < self._token_expiry - timedelta(minutes=5)):
            return self._token_cache
        
        # Solicitar nuevo token
        result = self.app.acquire_token_for_client(scopes=self.scope)
        
        if "access_token" in result:
            self._token_cache = result["access_token"]
            self._token_expiry = datetime.now() + timedelta(
                seconds=result.get("expires_in", 3600)
            )
            logger.debug("✅ Token de acceso renovado")
            return self._token_cache
        else:
            error_msg = result.get('error_description', result.get('error', 'Unknown'))
            logger.error(f"❌ Error obteniendo token: {error_msg}")
            raise Exception(f"Error de autenticación: {error_msg}")
    
    def _ensure_headers(self):
        """Asegura que los headers tengan el token actualizado"""
        token = self._get_access_token()
        self.headers['Authorization'] = f'Bearer {token}'
    
    def create_or_update(
        self, 
        entity: str, 
        key_field: str, 
        key_value: Any, 
        data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Crea o actualiza un registro (Upsert Inteligente)
        
        Args:
            entity: Nombre de la entidad (contacts, accounts, tasks, etc.)
            key_field: Campo por el que buscar (subject, jobtitle, name, etc.)
            key_value: Valor a buscar
            data: Datos a crear/actualizar
        
        Returns:
            {'id': 'guid', 'action': 'created' | 'updated'}
        """
        self._ensure_headers()
        
        # Escapar comillas simples
        safe_key_value = str(key_value).replace("'", "''")
        
        # ─────────────────────────────────────────────────────────
        # 1. DETERMINAR CAMPO ID
        # ─────────────────────────────────────────────────────────
        entity_key = entity.lower()
        entity_singular = entity[:-1] if entity.endswith('s') else entity
        id_field = self.ID_FIELD_MAPPING.get(
            entity_key, 
            entity_singular + "id"
        )
        
        # ─────────────────────────────────────────────────────────
        # 2. BUSCAR SI EXISTE
        # ─────────────────────────────────────────────────────────
        # ✅ CORRECCIÓN CLAVE: Usar params para codificación automática
        url = f"{self.base_url}/{entity}"
        
        search_params = {
            "$filter": f"{key_field} eq '{safe_key_value}'",
            "$select": id_field,
            "$top": 1
        }
        
        try:
            response = requests.get(
                url, 
                headers=self.headers, 
                params=search_params,
                timeout=30
            )
            response.raise_for_status()
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error buscando {entity}: {e.response.text}")
            raise
        except requests.exceptions.Timeout:
            logger.error("Timeout en búsqueda")
            raise Exception("Timeout conectando con Dynamics 365")
        
        existing = response.json().get('value', [])
        
        # ─────────────────────────────────────────────────────────
        # 3. ACTUALIZAR SI EXISTE
        # ─────────────────────────────────────────────────────────
        if existing:
            record_id = existing[0][id_field]
            update_url = f"{self.base_url}/{entity}({record_id})"
            
            try:
                response_update = requests.patch(
                    update_url, 
                    json=data, 
                    headers=self.headers,
                    timeout=30
                )
                response_update.raise_for_status()
                
                logger.info(f"✅ Actualizado {entity}: {key_value}")
                return {'id': record_id, 'action': 'updated'}
                
            except requests.exceptions.HTTPError as e:
                logger.error(f"Error actualizando {entity}: {e.response.text}")
                raise
        
        # ─────────────────────────────────────────────────────────
        # 4. CREAR SI NO EXISTE
        # ─────────────────────────────────────────────────────────
        else:
            try:
                response_create = requests.post(
                    url, 
                    json=data, 
                    headers=self.headers,
                    timeout=30
                )
                response_create.raise_for_status()
                
                # Extraer ID del header OData-EntityId
                new_id = None
                location = response_create.headers.get('OData-EntityId', '')
                match = re.search(r'\(([a-f0-9-]+)\)', location)
                
                if match:
                    new_id = match.group(1)
                
                # Fallback: intentar obtener del body
                if not new_id:
                    try:
                        body = response_create.json()
                        new_id = body.get(id_field)
                    except:
                        pass
                
                logger.info(f"✅ Creado {entity}: {key_value} (ID: {new_id})")
                return {'id': new_id, 'action': 'created'}
                
            except requests.exceptions.HTTPError as e:
                logger.error(f"Error creando {entity}: {e.response.text}")
                raise
    
    def get(
        self, 
        entity: str, 
        record_id: str, 
        select_fields: Optional[List[str]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Obtiene un registro por su ID
        """
        self._ensure_headers()
        
        try:
            url = f"{self.base_url}/{entity}({record_id})"
            
            params = {}
            if select_fields:
                params['$select'] = ','.join(select_fields)
            
            response = requests.get(
                url, 
                headers=self.headers, 
                params=params,
                timeout=30
            )
            
            if response.status_code == 404:
                return None
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            logger.error(f"Error obteniendo {entity}/{record_id}: {e}")
            return None
    
    def associate(
        self,
        entity: str,
        record_id: str,
        navigation_property: str,
        related_entity: str,
        related_id: str
    ) -> bool:
        """
        Asocia dos registros usando navigation properties de OData
        
        Args:
            entity: Entidad principal (ej: 'products')
            record_id: ID del registro principal
            navigation_property: Nombre de la propiedad de navegación (ej: 'crazy_Comercializadora')
            related_entity: Entidad relacionada (ej: 'accounts')
            related_id: ID del registro relacionado
            
        Returns:
            bool: True si la asociación fue exitosa
        """
        self._ensure_headers()
        
        try:
            # URL con navigation property y $ref
            url = f"{self.base_url}/{entity}({record_id})/{navigation_property}/$ref"
            
            # Payload con referencia al registro relacionado
            payload = {
                "@odata.id": f"{self.base_url}/{related_entity}({related_id})"
            }
            
            response = requests.put(
                url,
                json=payload,
                headers=self.headers,
                timeout=30
            )
            
            response.raise_for_status()
            logger.info(f"✅ Asociado {entity}({record_id}) -> {navigation_property} -> {related_entity}({related_id})")
            return True
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error asociando registros: {e.response.text if hasattr(e, 'response') else e}")
            raise
        except Exception as e:
            logger.error(f"Error en asociación: {e}")
            raise
    
    def query(
        self, 
        entity: str, 
        filter_query: Optional[str] = None,
        select_fields: Optional[List[str]] = None,

        top: int = 5000  # Por página (Dataverse limit)
    ) -> List[Dict[str, Any]]:
        """
        Consulta registros con filtros OData y paginación automática.
        
        Args:
            entity: Nombre de la entidad (tasks, contacts, etc.)
            filter_query: Filtro OData (ej: "contains(subject, 'Contrato')")
            select_fields: Campos a seleccionar
            top: Número de registros por página (default 5000, máximo de Dataverse)
            
        Returns:
            Lista COMPLETA de registros (todas las páginas)
            
        Note:
            Usa @odata.nextLink para paginación automática.
            Recorre todas las páginas hasta obtener todos los registros.

        """
        self._ensure_headers()
        
        all_results = []
        page_count = 0
        
        try:
            # URL inicial con parámetros
            url = f"{self.base_url}/{entity}"
            
            params = {'$top': top}
            
            if filter_query:
                params['$filter'] = filter_query
            
            if select_fields:
                params['$select'] = ','.join(select_fields)
            

            # ═══════════════════════════════════════════════════════════════
            # BUCLE DE PAGINACIÓN
            # ═══════════════════════════════════════════════════════════════
            while url:
                page_count += 1
                
                # Primera petición usa params, siguientes usan nextLink completo
                if page_count == 1:
                    response = requests.get(
                        url, 
                        headers=self.headers, 
                        params=params,
                        timeout=60
                    )
                else:
                    # nextLink ya incluye todos los parámetros
                    response = requests.get(
                        url, 
                        headers=self.headers,
                        timeout=60
                    )
                
                response.raise_for_status()
                data = response.json()
                
                # Acumular resultados
                page_results = data.get('value', [])
                all_results.extend(page_results)
                
                logger.info(f"   📄 Página {page_count}: {len(page_results)} registros (total: {len(all_results)})")
                
                # Verificar si hay más páginas
                next_link = data.get('@odata.nextLink')
                
                if next_link:
                    url = next_link
                else:
                    url = None  # Salir del bucle
            
            logger.info(f"✅ Query completada: {len(all_results)} registros en {page_count} página(s)")

            
            return all_results
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error HTTP en query {entity}: {e.response.status_code} - {e.response.text[:500]}")
            return []
        except Exception as e:

            logger.error(f"Error en consulta: {e}")
            return all_results if all_results else []


    
    def delete(self, entity: str, record_id: str) -> bool:
        """
        Elimina un registro
        """
        self._ensure_headers()
        
        try:
            url = f"{self.base_url}/{entity}({record_id})"
            
            response = requests.delete(url, headers=self.headers, timeout=30)
            response.raise_for_status()
            
            logger.info(f"✅ Eliminado {entity}: {record_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error eliminando {entity}: {e}")
            return False
    
    def update(self, entity: str, record_id: str, data: Dict[str, Any]) -> bool:
        """
        Actualiza un registro existente por su ID
        
        Args:
            entity: Nombre de la entidad
            record_id: ID del registro
            data: Datos a actualizar
        
        Returns:
            True si se actualiza correctamente
        """
        self._ensure_headers()
        
        try:
            url = f"{self.base_url}/{entity}({record_id})"
            
            # If-Match: * fuerza la actualización aunque el producto esté publicado
            update_headers = {**self.headers, 'If-Match': '*'}
            
            response = requests.patch(
                url, 
                json=data, 
                headers=update_headers,
                timeout=30
            )
            response.raise_for_status()
            
            logger.info(f"✅ Actualizado {entity}: {record_id}")
            return True
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error actualizando {entity}: {e.response.text}")
            raise
    
    def create(self, entity: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Crea un nuevo registro
        
        Args:
            entity: Nombre de la entidad
            data: Datos del nuevo registro
        
        Returns:
            {'id': 'nuevo_id'}
        """
        self._ensure_headers()
        
        try:
            url = f"{self.base_url}/{entity}"
            
            response = requests.post(
                url, 
                json=data, 
                headers=self.headers,
                timeout=30
            )
            response.raise_for_status()
            
            # Extraer ID del header OData-EntityId
            new_id = None
            location = response.headers.get('OData-EntityId', '')
            match = re.search(r'\(([a-f0-9-]+)\)', location)
            
            if match:
                new_id = match.group(1)
            
            # Fallback: intentar obtener del body
            if not new_id:
                try:
                    body = response.json()
                    # Intentar detectar el campo ID
                    entity_key = entity.lower()
                    entity_singular = entity[:-1] if entity.endswith('s') else entity
                    id_field = self.ID_FIELD_MAPPING.get(
                        entity_key, 
                        entity_singular + "id"
                    )
                    new_id = body.get(id_field)
                except:
                    pass
            
            logger.info(f"✅ Creado {entity} (ID: {new_id})")
            return {'id': new_id}
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"Error creando {entity}: {e.response.text}")
            raise
    
    def test_connection(self) -> bool:
        """
        Prueba la conexión con Dynamics 365
        """
        try:
            self._ensure_headers()
            
            url = f"{self.base_url}/WhoAmI"
            
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            user_id = data.get('UserId')
            
            logger.info(f"✅ Conexión exitosa. User ID: {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en test de conexión: {e}")
            return False


# ═══════════════════════════════════════════════════════════════
# SCRIPT DE PRUEBA
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    """
    Test del cliente Dataverse
    Ejecutar: python -m app.services.dataverse
    """
    
    print("="*60)
    print("🧪 TEST DE DATAVERSE CLIENT")
    print("="*60)
    
    try:
        # Inicializar
        dv = DataverseClient()
        
        # Test de conexión
        print("\n1️⃣ Probando conexión...")
        if dv.test_connection():
            print("   ✅ Conexión exitosa")
        else:
            print("   ❌ Error de conexión")
            exit(1)
        
        # Test de contacto
        print("\n2️⃣ Probando crear/actualizar contacto...")
        result = dv.create_or_update(
            "contacts",
            "jobtitle",
            "TEST12345678Z",
            {
                "firstname": "Test",
                "lastname": "Usuario",
                "jobtitle": "TEST12345678Z",
                "emailaddress1": "test@ejemplo.com"
            }
        )
        print(f"   Resultado: {result}")
        
        # Test de tarea
        print("\n3️⃣ Probando crear/actualizar tarea...")
        result = dv.create_or_update(
            "tasks",
            "subject",
            "Test Task",
            {
                "subject": "Test Task",
                "description": "Tarea de prueba desde Python",
                "prioritycode": 1
            }
        )
        print(f"   Resultado: {result}")
        
        print("\n" + "="*60)
        print("✅ TODOS LOS TESTS PASARON")
        print("="*60)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
