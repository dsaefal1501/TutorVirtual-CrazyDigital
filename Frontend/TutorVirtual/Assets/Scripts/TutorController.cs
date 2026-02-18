using UnityEngine;
using System.Collections;
using System.Collections.Generic;

[RequireComponent(typeof(Animator))]
public class TutorController : MonoBehaviour
{
	private Animator anim;

	[Header("Configuración de Parpadeo")]
	public float esperaMinima = 2f;
	public float esperaMaxima = 5f;
	public string nombreAnimacionBlink = "Blink"; 

	[Header("Configuración de Habla")]
	public string paramHablar = "Talk"; 

	// Diccionario para guardar el último estado ESTÁTICO de cada capas
	private Dictionary<int, string> lastStaticState = new Dictionary<int, string>();

	// Corutinas activas por capa (para poder cancelarlas si llega otra orden)
	private Dictionary<int, Coroutine> activeCoroutines = new Dictionary<int, Coroutine>();

	void Start()
	{
		anim = GetComponent<Animator>();
		
		if (anim == null)
		{
			Debug.LogError("TutorController: NO se encontró componente Animator.");
			return;
		}
		if (!anim.isHuman)
		{
			Debug.LogWarning("TutorController: El Animator NO está configurado como 'Humanoid'. La humanización procedimental no funcionará correctamente.");
		}
		
		// Inicializar estados estáticos por defecto (Idle con manos en Jarra)
		lastStaticState[AnimationsReference.BrowsLayerIndex] = AnimationsReference.Brows.None;
		
		// DEFAULT: Manos en Jarra para evitar que se quede 'colgado' o en Empty
		string defL = AnimationsReference.LHand.LHandJarra;
		string defR = AnimationsReference.RHand.RHandJarra;

		lastStaticState[AnimationsReference.LHandLayerIndex] = defL;
		lastStaticState[AnimationsReference.RHandLayerIndex] = defR;

		// Aplicar inmediatamente para que empiece así
		if (anim != null) 
		{
			anim.Play(defL, AnimationsReference.LHandLayerIndex);
			anim.Play(defR, AnimationsReference.RHandLayerIndex);
		}

		StartCoroutine(CicloAnimacionAleatoria());
	}

	// JS llamará a esto: window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 1);
	[Header("Configuración LipSync Manual")]
	public string animVocalA = "A";
	public string animVocalE = "E";
	public string animVocalO = "O";
	public string animSilencio = "Empty";
	public int mouthLayerIndex = 2; // CAPA DE LA BOCA (Ajustar en Inspector)
	public float velocidadLabios = 0.1f;
	
	private Coroutine _talkingCoroutine;

	public void SetTalkingState(int estado)
	{
		bool estaHablando = (estado == 1);

		// 1. Parametro Animator standard (opcional)
		if (anim != null) anim.SetBool(paramHablar, estaHablando);

		// 2. Corrutina de Lipsync
		if (estaHablando)
		{
			if (_talkingCoroutine == null) _talkingCoroutine = StartCoroutine(LipSyncLoop());
		}
		else
		{
			if (_talkingCoroutine != null) StopCoroutine(_talkingCoroutine);
			_talkingCoroutine = null;
			CerrarBoca();
		}
	}

	IEnumerator LipSyncLoop()
	{
		while (true)
		{
			float rnd = Random.value;
			string target = animSilencio;

			// Mapeo solicitado: A->A, E/I->E, O/U->O
			if (rnd < 0.35f) target = animVocalA;
			else if (rnd < 0.70f) target = animVocalE;
			else if (rnd < 0.90f) target = animVocalO;
			// 10% Silencio momentáneo

			if (anim != null) anim.CrossFade(target, 0.05f, mouthLayerIndex);

			yield return new WaitForSeconds(Random.Range(velocidadLabios * 0.8f, velocidadLabios * 1.5f));
		}
	}

	void CerrarBoca()
	{
		if (anim != null) anim.CrossFade(animSilencio, 0.15f, mouthLayerIndex);
	}

	public void SetExpression(string tag)
	{
		if (anim == null) return;
		tag = tag.Trim();

		string animationName = "";
		int layerIndex = -1;
		bool isDynamic = false;

		// --- 1. CEJAS (Brows) ---
		// --- 1. CEJAS (Brows) ---
		// CEJAS DINÁMICAS: Suben un momento y bajan solas
		if (tag == "[UpBrows]") { animationName = AnimationsReference.Brows.UpBrows; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = true; }
		else if (tag == "[RBrowUp]") { animationName = AnimationsReference.Brows.RBrowUp; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = true; }
		else if (tag == "[LBrowUp]") { animationName = AnimationsReference.Brows.LBrowUp; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = true; }
		// CEJAS ESTÁTICAS (Reset manual o estado base)
		else if (tag == "[NoneBrows]") { animationName = AnimationsReference.Brows.None; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = false; }

		// --- 2. MANO IZQUIERDA (LHand) ---
		else if (System.Array.Exists(AnimationsReference.LHand.Dinamicos, x => tag == $"[{x}]")) 
		{ 
			animationName = tag.Trim('[', ']'); layerIndex = AnimationsReference.LHandLayerIndex; isDynamic = true; 
		}
		else if (System.Array.Exists(AnimationsReference.LHand.Estaticos, x => tag == $"[{x}]"))
		{ 
			animationName = tag.Trim('[', ']'); layerIndex = AnimationsReference.LHandLayerIndex; isDynamic = false;
		}

		// --- 3. MANO DERECHA (RHand) ---
		else if (System.Array.Exists(AnimationsReference.RHand.Dinamicos, x => tag == $"[{x}]"))
		{
			animationName = tag.Trim('[', ']'); layerIndex = AnimationsReference.RHandLayerIndex; isDynamic = true;
		}
		else if (System.Array.Exists(AnimationsReference.RHand.Estaticos, x => tag == $"[{x}]"))
		{
			string cleaned = tag.Trim('[', ']');
			if (tag == "[RHandJarra]") cleaned = AnimationsReference.RHand.RHandJarra;
			animationName = cleaned; layerIndex = AnimationsReference.RHandLayerIndex; isDynamic = false;
		}


		// EJECUCIÓN LÓGICA GENERAL
		if (!string.IsNullOrEmpty(animationName) && layerIndex >= 0)
		{
			// A) GESTIÓN DE CORUTINAS (Cancelar reset pendiente si llega nueva orden a la misma capa)
			if (activeCoroutines.ContainsKey(layerIndex) && activeCoroutines[layerIndex] != null)
			{
				StopCoroutine(activeCoroutines[layerIndex]);
				activeCoroutines[layerIndex] = null;
			}

			// B) APLICAR ANIMACIÓN PRINCIPAL
			if (isDynamic)
			{
				// Reproducir dyn y luego volver al último estático
				anim.CrossFade(animationName, 0.2f, layerIndex);
				activeCoroutines[layerIndex] = StartCoroutine(ResetToStaticAfterDelay(layerIndex, 2.5f)); 
			}
			else
			{
				// Es un nuevo estado ESTÁTICO. 
				// AQUÍ APLICAMOS LA LÓGICA DE SIMETRÍA (Igualar manos)
				
				ApplyStaticPoseSymmetry(layerIndex, animationName);
			}
		}
	}

	// Método helper para forzar simetría en poses estáticas (Jarra/Crossed)
	private void ApplyStaticPoseSymmetry(int primaryLayer, string primaryAnimName)
	{
		// 1. Aplicar a la mano principal
		lastStaticState[primaryLayer] = primaryAnimName;
		anim.CrossFade(primaryAnimName, 0.25f, primaryLayer);

		// 2. Determinar la mano "espejo" y la animación correspondiente
		int mirrorLayer = -1;
		string mirrorAnimName = "";

		// Caso: Mano Izquierda manda -> Afecta Derecha
		if (primaryLayer == AnimationsReference.LHandLayerIndex)
		{
			mirrorLayer = AnimationsReference.RHandLayerIndex;
			if (primaryAnimName == AnimationsReference.LHand.LHandJarra) mirrorAnimName = AnimationsReference.RHand.RHandJarra;
			else if (primaryAnimName == AnimationsReference.LHand.LHandCrossed) mirrorAnimName = AnimationsReference.RHand.RHandCrossed;
		}
		// Caso: Mano Derecha manda -> Afecta Izquierda
		else if (primaryLayer == AnimationsReference.RHandLayerIndex)
		{
			mirrorLayer = AnimationsReference.LHandLayerIndex;
			if (primaryAnimName == AnimationsReference.RHand.RHandJarra) mirrorAnimName = AnimationsReference.LHand.LHandJarra;
			else if (primaryAnimName == AnimationsReference.RHand.RHandCrossed) mirrorAnimName = AnimationsReference.LHand.LHandCrossed;
		}

		// 3. Aplicar a la mano espejo si encontramos correspondencia
		if (mirrorLayer != -1 && !string.IsNullOrEmpty(mirrorAnimName))
		{
			// Cancelar corutinas en la mano espejo también (para que no vuelva a un estado viejo)
			if (activeCoroutines.ContainsKey(mirrorLayer) && activeCoroutines[mirrorLayer] != null)
			{
				StopCoroutine(activeCoroutines[mirrorLayer]);
				activeCoroutines[mirrorLayer] = null;
			}

			// Actualizar estado y animar
			lastStaticState[mirrorLayer] = mirrorAnimName;
			anim.CrossFade(mirrorAnimName, 0.25f, mirrorLayer);
			// Debug.Log($"[Symmetry] Forzando {mirrorAnimName} en capa {mirrorLayer} por coherencia.");
		}
	}

	IEnumerator ResetToStaticAfterDelay(int layerIndex, float delay)
	{
		yield return new WaitForSeconds(delay);
		
		// Recuperar el último estado estático conocido
		if (lastStaticState.ContainsKey(layerIndex))
		{
			string staticState = lastStaticState[layerIndex];
			if (!string.IsNullOrEmpty(staticState))
			{
				anim.CrossFade(staticState, 0.5f, layerIndex);
			}
		}
		activeCoroutines[layerIndex] = null;
	}

	// --- HUMANIZACIÓN MANUAL COMPLETA (SIN HUMANOID) ---
	[Header("Humanización Procedimental")]
	public bool usarHumanizacion = true;
	
	[Header("ASIGNACIÓN OBLIGATORIA DE HUESOS")]
	[Tooltip("Hueso del pecho o columna")]
	public Transform spineBone; 
	[Tooltip("Hueso del cuello")]
	public Transform neckBone;
	[Tooltip("Hueso de la cabeza")]
	public Transform headBone;     
	[Tooltip("Ojo Izquierdo (Opcional, si quieres movimiento detallado)")]
	public Transform leftEyeBone;
	[Tooltip("Ojo Derecho (Opcional, si quieres movimiento detallado)")]
	public Transform rightEyeBone;

	[Header("Configuración Mirada")]
	public Transform objetivoMirada;
	public Transform ojetivoOjos; // Nuevo campo para ojos independientes
	[Range(0f, 1f)] public float pesoMiradaHead = 0.4f; // Cuánto gira la cabeza
	[Range(0f, 1f)] public float pesoMiradaNeck = 0.3f; // Cuánto gira el cuello
	[Range(0f, 1f)] public float pesoMiradaEyes = 0.8f; // Cuánto giran los ojos (si están asignados)
	
	[Header("Configuración Balanceo")]
	public float velocidadSway = 0.6f; 
	public float amplitudSway = 1.0f;
	
	[Header("Configuración Ojos Inquietos")]
	[Range(0.01f, 0.5f)] public float saccadeRadius = 0.15f; // Cuánto se desvían los ojos
	[Range(0.1f, 5.0f)] public float saccadeIntervalMin = 0.5f; 
	[Range(0.1f, 5.0f)] public float saccadeIntervalMax = 2.5f;

	// Variables internas
	private float _tiempoSeed;
	private Vector3 _offsetMiradaActual;
	private Vector3 _currentSmoothedOffset;
	private float _timerSaccade;
	
	// Rotaciones previas para cancelar acumulación
	private Quaternion _lastSpineSway = Quaternion.identity; 

	void LateUpdate()
	{
		if (!usarHumanizacion || anim == null) return;
		
		// Si no hay target, usar cámara
		if (objetivoMirada == null && Camera.main != null) objetivoMirada = Camera.main.transform;

		// 1. SWAY (BALANCEO DE COLUMNA)
		ApplySpineSway();

		// 2. MIRADA (HEAD/NECK TRACKING & EYES)
		if (objetivoMirada != null)
		{
			UpdateSaccades();
			
			// Target General (Cabeza/Cuello)
			Vector3 targetPoint = objetivoMirada.position + _currentSmoothedOffset;
			
			// Target Ojos (Específico o General)
			Vector3 targetPointEyes = (ojetivoOjos != null ? ojetivoOjos.position : targetPoint) + _currentSmoothedOffset;
			// Nota: Si ojetivoOjos != null, sumamos offset de nuevo? 
			// Si targetPoint ya tiene offset, duplicarlo puede ser mucho.
			// Corrección:
			if (ojetivoOjos != null) targetPointEyes = ojetivoOjos.position + _currentSmoothedOffset;
			else targetPointEyes = targetPoint; // Ya incluye offset

			// A) Mover Cuello (Un poco)
			RotateBoneTowards(neckBone, targetPoint, pesoMiradaNeck);
			
			// B) Mover Cabeza (Más)
			RotateBoneTowards(headBone, targetPoint, pesoMiradaHead);
			
			// C) Mover Ojos (Mucho)
			if (leftEyeBone != null) RotateBoneTowards(leftEyeBone, targetPointEyes, pesoMiradaEyes);
			if (rightEyeBone != null) RotateBoneTowards(rightEyeBone, targetPointEyes, pesoMiradaEyes);
		}
	}

	void ApplySpineSway()
	{
		if (spineBone == null) return;

		// A. Limpiar frame anterior
		spineBone.localRotation = spineBone.localRotation * Quaternion.Inverse(_lastSpineSway);

		// B. Calcular frame actual
		_tiempoSeed += Time.deltaTime * velocidadSway;
		float swayX = (Mathf.PerlinNoise(_tiempoSeed, 10f) - 0.5f) * amplitudSway; 
		float swayY = (Mathf.PerlinNoise(10f, _tiempoSeed) - 0.5f) * (amplitudSway * 0.7f); 
		float breathing = Mathf.Sin(Time.time * 1.5f) * 0.3f; 

		Quaternion newSway = Quaternion.Euler(swayY + breathing, swayX, 0);

		// C. Aplicar
		spineBone.localRotation = spineBone.localRotation * newSway;
		_lastSpineSway = newSway;
	}

	void RotateBoneTowards(Transform bone, Vector3 targetPos, float weight)
	{
		if (bone == null || weight <= 0.001f) return;

		Vector3 direction = targetPos - bone.position;
		if (direction != Vector3.zero)
		{
			Quaternion targetRot = Quaternion.LookRotation(direction, Vector3.up);
			// Slerp con suavidad
			bone.rotation = Quaternion.Slerp(bone.rotation, targetRot, weight * Time.deltaTime * 10f);
		}
	}

	void UpdateSaccades()
	{
		_timerSaccade -= Time.deltaTime;
		if (_timerSaccade <= 0)
		{
			// Ojos inquietos (Saccades)
			float radioDesvio = Random.Range(0.01f, saccadeRadius); 
			_offsetMiradaActual = (Random.insideUnitSphere * radioDesvio); 
			
			// Mantener en el plano relativo al frente (opcional, aquí sphere random está bien)
			// _offsetMiradaActual.z = 0; 
			
			// Siguiente movimiento en...
			_timerSaccade = Random.Range(saccadeIntervalMin, saccadeIntervalMax);
		}
		_currentSmoothedOffset = Vector3.Lerp(_currentSmoothedOffset, _offsetMiradaActual, Time.deltaTime * 8f); // Movimiento de ojos rápido
	}

	IEnumerator CicloAnimacionAleatoria()
	{
		while (true)
		{
			float tiempoEspera = Random.Range(esperaMinima, esperaMaxima);
			yield return new WaitForSeconds(tiempoEspera);

			if (anim != null)
			{
				anim.Play(nombreAnimacionBlink, -1, 0f);
			}
		}
	}
}