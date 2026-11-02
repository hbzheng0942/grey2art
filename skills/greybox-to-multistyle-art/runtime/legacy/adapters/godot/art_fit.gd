extends RefCounted
# Explicit local edits in object space. Texture resources remain shared.
func band(value: float, length_: float, desired: float, lower: float=.22, upper: float=.80) -> Vector2:
	var lo=length_*lower;var hi=length_*upper
	var slope=(desired-length_*(1.-upper+lower))/(length_*(upper-lower))
	if slope <= .08: return Vector2(value*desired/length_,desired/length_)
	if value < lo: return Vector2(value,1.)
	if value > hi: return Vector2(value+desired-length_,1.)
	return Vector2(lo+(value-lo)*slope,slope)

func fit(node: Node3D, bounds: AABB, target: Vector3, family: String, variant: String, parent: Transform3D=Transform3D.IDENTITY, controls: Dictionary={}) -> void:
	var transform: Transform3D=parent*node.transform
	var scale_xz=minf(target.x/bounds.size.x,target.z/bounds.size.z)
	# Planter trough depth is a local manufacturing dimension; preserve width/height.
	var shallow=family=="barrier"
	var sx=target.x/bounds.size.x if shallow else scale_xz
	var sz=target.z/bounds.size.z if shallow else scale_xz
	var source_h=bounds.size.y*scale_xz
	if node is MeshInstance3D and node.mesh!=null:
		var mesh=ArrayMesh.new()
		for surface in node.mesh.get_surface_count():
			var arrays=node.mesh.surface_get_arrays(surface)
			var vertices: PackedVector3Array=arrays[Mesh.ARRAY_VERTEX]
			var normals: PackedVector3Array=arrays[Mesh.ARRAY_NORMAL]
			var tangents: PackedFloat32Array=arrays[Mesh.ARRAY_TANGENT] if arrays[Mesh.ARRAY_TANGENT]!=null else PackedFloat32Array()
			for i in vertices.size():
				var v=transform*vertices[i]
				v-=Vector3(bounds.get_center().x,bounds.position.y,bounds.get_center().z)
				var ymap=band(v.y*scale_xz,source_h,target.y)
				# Preserve the gyro rings and rounded warehouse roof as rigid upper geometry.
				if family=="gyro":ymap=band(v.y*scale_xz,source_h,target.y,.12,.38)
				if family=="dome":ymap=band(v.y*scale_xz,source_h,target.y,.08,.30)
				if family=="drum":
					# Reuse the warehouse shell, but give the small drum a tall cylindrical body and low cap.
					var split=source_h*.44;var raw_y=v.y*scale_xz
					if raw_y<=split:ymap=Vector2(raw_y*target.y*.78/split,target.y*.78/split)
					else:ymap=Vector2(target.y*.78+(raw_y-split)*target.y*.22/(source_h-split),target.y*.22/(source_h-split))
				if controls.has("band"):
					var limits: Array=controls["band"]
					ymap=band(v.y*scale_xz,source_h,target.y,float(limits[0]),float(limits[1]))
				var xmap=Vector2(v.x*sx,sx)
				if family=="bench":
					var b=band((v.x+bounds.size.x*.5)*scale_xz,bounds.size.x*scale_xz,target.x)
					xmap=Vector2(b.x-target.x*.5,b.y*scale_xz)
				v=Vector3(xmap.x,ymap.x,v.z*sz)
				var derivative=Vector3(xmap.y,ymap.y*scale_xz,sz)
				# Plain porcelain boundary variant has a low flat top; retain the generated trough below.
				if family=="barrier" and variant=="plain":
					v.y=minf(v.y/.53,target.y)
				vertices[i]=v
				if normals.size()>i:
					var n=(transform.basis.inverse().transposed()*normals[i])/derivative
					normals[i]=n.normalized()
				if tangents.size()>i*4+3:
					var t=transform.basis*Vector3(tangents[i*4],tangents[i*4+1],tangents[i*4+2])*derivative
					if normals.size()>i:t-=normals[i]*t.dot(normals[i])
					t=t.normalized();tangents[i*4]=t.x;tangents[i*4+1]=t.y;tangents[i*4+2]=t.z
			arrays[Mesh.ARRAY_VERTEX]=vertices;arrays[Mesh.ARRAY_NORMAL]=normals
			if not tangents.is_empty():arrays[Mesh.ARRAY_TANGENT]=tangents
			mesh.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES,arrays)
			# Geometry fitting preserves source materials. Style changes are explicit
			# in the factory after this static-mesh operation.
			mesh.surface_set_material(surface,node.mesh.surface_get_material(surface))
		node.mesh=mesh
	for child in node.get_children():
		if child is Node3D:fit(child,bounds,target,family,variant,transform,controls)
	node.transform=Transform3D.IDENTITY
