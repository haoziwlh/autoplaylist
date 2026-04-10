class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/af/d5/8497fdeed899d8f9bc066851a3a91b819c497c1534b66df6c5c1ef2e22ac/myplaylist-0.4.0-py3-none-any.whl",,,,,,,,,,,,,,,,,,,,,,
      using: :nounzip
  sha256 "8ee70ff08c49cf4e98244aac277085995ed56382da5049611b2bf9112152da5d"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
