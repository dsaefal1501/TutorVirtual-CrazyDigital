using UnityEngine;

public class BackgroundMode : MonoBehaviour
{
	void Start()
	{
		// Solo se ejecuta en la versión WebGL exportada
        #if !UNITY_EDITOR && UNITY_WEBGL
        
		// Esta línea es la clave: Libera el teclado para que funcione el HTML
		UnityEngine.WebGLInput.captureAllKeyboardInput = false;
        
		// Opcional: Si usas el New Input System y quieres asegurarte 
		// de que no procese nada, puedes desactivarlo aquí también, 
		// aunque la línea de arriba suele bastar.
        
        #endif
	}
}