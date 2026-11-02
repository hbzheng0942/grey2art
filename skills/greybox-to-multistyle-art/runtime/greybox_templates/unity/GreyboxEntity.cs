using UnityEngine;

namespace GreyboxHarnessV05
{
    // This component is the join between semantic knowledge and real scene
    // objects. Visual replacement never owns the Logic/Collision children.
    public sealed class GreyboxEntity : MonoBehaviour
    {
        public string stableId;
        public string semanticRole;
        public string behavior;
        public string label;
        public string[] tags;
        public Vector3 interactionAnchor;
        public Transform logic;
        public Transform anchor;
        public Transform collisionOwner;
        public Transform visual;
        public Collider collision;
        public bool consumed;
        public Vector3 InteractionWorldAnchor { get { return anchor != null ? anchor.position : interactionAnchor; } }
        public void ResetEntity()
        {
            consumed = false;
            if (visual != null) visual.gameObject.SetActive(true);
            if (collision != null) collision.enabled = true;
        }
        public void Consume()
        {
            consumed = true;
            if (visual != null) visual.gameObject.SetActive(false);
            if (collision != null) collision.enabled = false;
        }
    }
}
