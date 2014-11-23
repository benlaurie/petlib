from bindings import _FFI, _C
from functools import wraps
from copy import copy
from binascii import hexlify
from bn import Bn

class EcGroup(object):

  @staticmethod
  def list_curves():
    """Return a dictionary of nid -> curve names"""
    size_t = int(_C.EC_get_builtin_curves(_FFI.NULL, 0))
    assert 0 < size_t 
    names = _FFI.new("EC_builtin_curve[]", size_t)
    _C.EC_get_builtin_curves(names, size_t)

    all_curves = []
    for i in range(size_t):
      all_curves +=  [(int(names[i].nid), str(_FFI.string(names[i].comment)))]
    return dict(all_curves)
  
  def __init__(self, nid, optimize_mult=True):
    """Build an EC group from the Open SSL nid"""
    self.ecg = _C.EC_GROUP_new_by_curve_name(nid)
    if optimize_mult:
      assert _C.EC_GROUP_precompute_mult(self.ecg, _FFI.NULL)

  def generator(self):
    """Returns the generator of the EC group"""
    g = EcPt(self)
    internal_g = _C.EC_GROUP_get0_generator(self.ecg)
    assert _C.EC_POINT_copy(g.pt, internal_g)
    return g

  def infinite(self):
    """Returns a point at infinity"""
    zero = EcPt(self)
    assert _C.EC_POINT_set_to_infinity(self.ecg, zero.pt)
    return zero

  def order(self):
    """Returns the order of the group as a Big Number"""
    o = Bn()
    assert _C.EC_GROUP_get_order(self.ecg, o.bn, _FFI.NULL)
    return o

  def __eq__(self, other):
    res = _C.EC_GROUP_cmp(self.ecg, other.ecg, _FFI.NULL);
    return res == 0

  def __ne__(self, other):
    return not self.__eq__(other)

  def nid(self):
    """Returns the Open SSL group ID"""
    return int(_C.EC_GROUP_get_curve_name(self.ecg))

  def __del__(self):
    _C.EC_GROUP_free(self.ecg);

  def check_point(self, pt):
    """Ensures the point is on the curve"""
    res = int(_C.EC_POINT_is_on_curve(self.ecg, pt.pt, _FFI.NULL))
    return res == 1


# int EC_POINT_is_at_infinity(const EC_GROUP *, const EC_POINT *);
# int EC_POINT_is_on_curve(const EC_GROUP *, const EC_POINT *, BN_CTX *);

# int EC_POINT_make_affine(const EC_GROUP *, EC_POINT *, BN_CTX *);
# int EC_POINTs_make_affine(const EC_GROUP *, size_t num, EC_POINT *[], BN_CTX *);


# int EC_POINTs_mul(const EC_GROUP *, EC_POINT *r, const BIGNUM *, size_t num, const EC_POINT *[], const BIGNUM *[], BN_CTX *);



class EcPt(object):
  """An EC point, supporting point addition, doubling 
  and multiplication with a scalar
  """
  __slots__ = ["pt", "group"]
  
  @staticmethod
  def from_binary(sbin, group):
    "Create a point from a string binary sequence"
    new_pt = EcPt(group)
    assert _C.EC_POINT_oct2point(group.ecg, new_pt.pt, sbin, len(sbin), _FFI.NULL)
    return new_pt

  def __init__(self, group):
    self.group = group
    self.pt = _C.EC_POINT_new(group.ecg)

  def __copy__(self):
    new_point = EcPt(self.group)
    assert _C.EC_POINT_copy(new_point.pt, self.pt)
    return new_point

  def __add__(self, other):
    assert type(other) == EcPt
    assert other.group == self.group
    result = EcPt(self.group)
    assert _C.EC_POINT_add(self.group.ecg, result.pt, self.pt, other.pt, _FFI.NULL)
    return result

  def double(self):
    """Doubles the point. equivalent to "self + self".
    """
    result = EcPt(self.group)
    assert _C.EC_POINT_dbl(self.group.ecg, result.pt, self.pt, _FFI.NULL)
    return result

  def __neg__(self):
    result = copy(self)
    assert _C.EC_POINT_invert(self.group.ecg, result.pt, _FFI.NULL)
    return result

  def __rmul__(self, other):
    assert type(other) == Bn
    result = EcPt(self.group)
    assert _C.EC_POINT_mul(self.group.ecg, result.pt, _FFI.NULL, self.pt, other.bn, _FFI.NULL)
    return result

  def __eq__(self, other):
    assert type(other) == EcPt
    assert other.group == self.group
    r = int(_C.EC_POINT_cmp(self.group.ecg, self.pt, other.pt, _FFI.NULL))
    return r == 0

  def __ne__(self, other):
    return not self.__eq__(other)

  def __del__(self):
    _C.EC_POINT_clear_free(self.pt)

  def export(self):
    """Returns a string binary representation of the point"""
    # size_t EC_POINT_point2oct(const EC_GROUP *, const EC_POINT *, point_conversion_form_t form,
    #         unsigned char *buf, size_t len, BN_CTX *);
    size = _C.EC_POINT_point2oct(self.group.ecg, self.pt, _C.POINT_CONVERSION_COMPRESSED, 
               _FFI.NULL, 0, _FFI.NULL)
    buf = _FFI.new("unsigned char[]", size)
    _C.EC_POINT_point2oct(self.group.ecg, self.pt, _C.POINT_CONVERSION_COMPRESSED,
               buf, size, _FFI.NULL)
    output = str(_FFI.buffer(buf)[:])
    return output

def test_ec_list_group():
  c = EcGroup.list_curves()
  assert len(c) > 0 
  assert 409 in c
  assert 410 in c

def test_ec_build_group():
  G = EcGroup(409)
  H = EcGroup(410)
  assert G.check_point(G.generator())
  assert not H.check_point(G.generator())
  order = G.order()
  assert str(order) == "6277101735386680763835789423176059013767194773182842284081"
  assert G == G
  assert not (G == H)
  assert G != H
  assert not (G != G)

def test_ec_arithmetic():
  G = EcGroup(409)
  g = G.generator()
  assert g + g == g + g  
  assert g + g == g.double()
  assert g + g == Bn(2) * g  
   
  assert g + g != g + g + g 
  assert g + (-g) == G.infinite()

def test_ec_io():
  G = EcGroup(409)
  g = G.generator()
  assert len(g.export()) == 25
  i = G.infinite()
  assert len(i.export()) == 1
  assert EcPt.from_binary(g.export(), G) == g
  assert EcPt.from_binary(i.export(), G) == i
