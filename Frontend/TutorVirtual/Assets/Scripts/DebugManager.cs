using UnityEngine;
using TMPro;

public class DebugManager : MonoBehaviour
{
	[SerializeField] private TextMeshProUGUI fpsText;
    
	[Header("Configuración")]
	[Tooltip("Frecuencia de actualización del texto en segundos")]
	[SerializeField] private float frecuenciaActualizacion = 0.5f;

	private float tiempoAcumulado = 0f;
	private int cuadrosContados = 0;

	void Awake()
	{
		// 1. Desactivamos VSync para tener control manual
		QualitySettings.vSyncCount = 0;
        
		// 2. Limitamos a 60 FPS para optimizar rendimiento/batería
		Application.targetFrameRate = 30;
	}

	void Update()
	{
		// Lógica del contador de FPS
		tiempoAcumulado += Time.unscaledDeltaTime;
		cuadrosContados++;

		if (tiempoAcumulado >= frecuenciaActualizacion)
		{
			float fps = cuadrosContados / tiempoAcumulado;
            
			if (fpsText != null)
			{
				fpsText.text = $"FPS: {fps:F0}";

				// Colores semáforo
				if (fps >= 25) fpsText.color = Color.green;
				else if (fps >= 15) fpsText.color = Color.yellow;
				else fpsText.color = Color.red;
			}

			tiempoAcumulado = 0f;
			cuadrosContados = 0;
		}
	}
}